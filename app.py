from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from googletrans import Translator
from gtts import gTTS
import speech_recognition as sr
import os
import tempfile
import base64
import logging
import json
import requests
import time
import uuid
from better_profanity import profanity
from functools import lru_cache
import hashlib
from datetime import datetime
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='frontend')
CORS(app)

# Initialize translator
try:
    translator = Translator()
except Exception as e:
    logger.error(f"Failed to initialize translator: {str(e)}")
    translator = None

# Load profanity filter with default words
profanity.load_censor_words()

# Dictionary of supported languages
LANGUAGES = {
    'en': 'English',
    'es': 'Spanish',
    'fr': 'French',
    'de': 'German',
    'it': 'Italian',
    'pt': 'Portuguese',
    'ru': 'Russian',
    'ja': 'Japanese',
    'ko': 'Korean',
    'zh-cn': 'Chinese (Simplified)',
    # Indian languages
    'hi': 'Hindi',
    'bn': 'Bengali',
    'te': 'Telugu',
    'ta': 'Tamil',
    'mr': 'Marathi',
    'gu': 'Gujarati',
    'kn': 'Kannada',
    'ml': 'Malayalam',
    'pa': 'Punjabi',
    'ur': 'Urdu',
}

# Dictionary API endpoints
DICTIONARY_API_URL = "https://api.dictionaryapi.dev/api/v2/entries/{lang}/{word}"
URBAN_DICTIONARY_API_URL = "https://api.urbandictionary.com/v0/define?term={word}"
WORDS_API_URL = "https://wordsapiv1.p.rapidapi.com/words/{word}"

# WordsAPI headers - You would need to sign up for a free API key at RapidAPI
WORDS_API_HEADERS = {
    'x-rapidapi-host': "wordsapiv1.p.rapidapi.com",
    'x-rapidapi-key': "SIGN_UP_FOR_KEY"  # Replace with your actual API key if available
}

# 2. Add a cache with TTL for translations and definitions
CACHE = {}
CACHE_TTL = 86400  # 24 hours in seconds

def get_cache_key(prefix, *args):
    """Generate a unique cache key based on function arguments."""
    key_string = prefix + '_' + '_'.join(str(arg) for arg in args)
    return hashlib.md5(key_string.encode()).hexdigest()

def get_from_cache(key):
    """Get item from cache if it exists and is not expired."""
    if key in CACHE:
        timestamp, data = CACHE[key]
        if datetime.now().timestamp() - timestamp < CACHE_TTL:
            return data
    return None

def save_to_cache(key, data):
    """Save item to cache with current timestamp."""
    CACHE[key] = (datetime.now().timestamp(), data)

# 3. Add rate limiting for API protection
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

def is_appropriate_definition(text):
    """Check if a definition is appropriate and formal using better_profanity."""
    if not text:
        return False
    
    # Check if it's too short to be a proper definition
    if len(text.split()) < 3:
        return False
    
    # Check for profanity
    if profanity.contains_profanity(text):
        return False
    
    return True

def remove_bad_definitions(definitions, part_of_speech):
    """Removes definitions containing profanity and formats them properly."""
    clean_defs = []
    
    for definition in definitions:
        def_text = definition.get('definition', '')
        
        # Skip definitions with profanity
        if not is_appropriate_definition(def_text):
            continue
        
        def_obj = {
            'definition': def_text,
            'part_of_speech': part_of_speech,
        }
        
        # Add example if available and appropriate
        if 'example' in definition:
            example_text = definition['example']
            if not profanity.contains_profanity(example_text):
                def_obj['example'] = example_text
        
        clean_defs.append(def_obj)
    
    return clean_defs

@app.route('/')
def serve_frontend():
    """Serve the main frontend HTML file."""
    return send_from_directory('frontend', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    """Serve static files from the frontend directory."""
    return send_from_directory('frontend', path)

@app.route('/api/languages', methods=['GET'])
def get_languages():
    """Return the list of supported languages."""
    return jsonify(LANGUAGES)

def generate_pronunciation(text, lang):
    """Generate pronunciation audio and return as base64."""
    if not text or not lang:
        logger.warning("Missing text or language for pronunciation")
        return None
        
    try:
        # Create a unique filename to avoid conflicts
        unique_filename = f"temp_audio_{uuid.uuid4().hex}.mp3"
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, unique_filename)
        
        logger.info(f"Generating pronunciation for '{text[:20]}...' in language '{lang}'")
        
        # Generate the audio file
        tts = gTTS(text=text, lang=lang, slow=False)
        
        # Use a retry mechanism for saving the file to handle potential issues
        max_retries = 3
        for attempt in range(max_retries):
            try:
                tts.save(file_path)
                # Add a small delay to ensure file is fully written
                time.sleep(0.2)
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Attempt {attempt+1} failed to save audio file: {str(e)}. Retrying...")
                    time.sleep(0.5)  # Wait longer before retry
                else:
                    raise
        
        # Read the file and convert to base64 with explicit handling
        try:
            with open(file_path, 'rb') as audio_file:
                audio_data = audio_file.read()
                if not audio_data:
                    raise ValueError("Generated audio file is empty")
                audio_base64 = base64.b64encode(audio_data).decode('utf-8')
        except Exception as e:
            logger.error(f"Failed to read audio file: {str(e)}")
            raise
        finally:
            # Always try to clean up, but don't fail if we can't
            try:
                # Make sure file handle is closed before attempting removal
                if 'audio_file' in locals() and not audio_file.closed:
                    audio_file.close()
                    
                # Small delay before removing to ensure no file locks
                time.sleep(0.1)
                os.remove(file_path)
            except Exception as e:
                logger.warning(f"Could not remove temporary file {file_path}: {str(e)}")
        
        return audio_base64
    except Exception as e:
        logger.error(f"Failed to generate pronunciation: {str(e)}")
        # Return None rather than raising to prevent API failure
        return None

# 4. Add a history endpoint to track recent searches
SEARCH_HISTORY = []
MAX_HISTORY_SIZE = 50

@app.route('/api/history', methods=['GET'])
def get_search_history():
    """Return search history."""
    return jsonify(SEARCH_HISTORY)

@app.route('/api/clear-history', methods=['POST'])
def clear_search_history():
    """Clear search history."""
    global SEARCH_HISTORY
    SEARCH_HISTORY = []
    return jsonify({"status": "success", "message": "History cleared"})

# 5. Improve the search_word function with caching
@app.route('/api/search', methods=['POST'])
@limiter.limit("30 per minute")  # Add rate limiting
def search_word():
    """Search for a word's definition, translation, and pronunciation."""
    if not request.is_json:
        return jsonify({'error': 'Request must be JSON'}), 400
    
    data = request.json
    word = data.get('word')
    target_lang = data.get('target_lang', 'en')
    
    if not word:
        return jsonify({'error': 'Word is required'}), 400
    
    if target_lang not in LANGUAGES:
        return jsonify({'error': f'Unsupported language: {target_lang}'}), 400
    
    # Check cache first
    cache_key = get_cache_key('search', word, target_lang)
    cached_result = get_from_cache(cache_key)
    if cached_result:
        logger.info(f"Cache hit for word: {word} in {target_lang}")
        return jsonify(cached_result)
    
    try:
        logger.info(f"Searching for word: {word} in {target_lang}")
        
        result = {
            'word': word,
            'target_language': target_lang,
            'definitions': [],
            'examples': [],
            'synonyms': [],
            'antonyms': [],
            'phonetics': [],
            'audio': None,
            'translation': None,
            'source_language': 'en',
            'pronunciation': None,
            'translation_pronunciation': None,
            'translated_definitions': [],
            'translated_examples': []
        }
        
        # Get dictionary definition for source language (English or detected)
        if target_lang == 'en':
            # Try the Free Dictionary API first
            try:
                dict_response = requests.get(DICTIONARY_API_URL.format(lang=target_lang, word=word))
                if dict_response.status_code == 200:
                    dict_data = dict_response.json()
                    
                    if dict_data and len(dict_data) > 0:
                        entry = dict_data[0]
                        
                        # Get phonetics
                        if 'phonetics' in entry and entry['phonetics']:
                            for phonetic in entry['phonetics']:
                                phonetic_obj = {
                                    'text': phonetic.get('text', ''),
                                }
                                
                                # Get audio if available
                                if phonetic.get('audio') and not result['audio']:
                                    result['audio'] = phonetic.get('audio')
                                
                                result['phonetics'].append(phonetic_obj)
                        
                        # Get meanings
                        if 'meanings' in entry:
                            for meaning in entry['meanings']:
                                part_of_speech = meaning.get('partOfSpeech', '')
                                
                                # Get definitions and filter out inappropriate ones
                                if 'definitions' in meaning:
                                    clean_definitions = remove_bad_definitions(meaning['definitions'], part_of_speech)
                                    result['definitions'].extend(clean_definitions)
                                    
                                    # Add examples to the examples list
                                    for def_obj in clean_definitions:
                                        if 'example' in def_obj:
                                            result['examples'].append(def_obj['example'])
                                
                                # Get synonyms
                                if 'synonyms' in meaning and meaning['synonyms']:
                                    result['synonyms'].extend(meaning['synonyms'])
                                
                                # Get antonyms
                                if 'antonyms' in meaning and meaning['antonyms']:
                                    result['antonyms'].extend(meaning['antonyms'])
            except Exception as e:
                logger.error(f"Error fetching dictionary data: {str(e)}")
            
            # Try WordsAPI if available and no definitions found
            if not result['definitions'] and WORDS_API_HEADERS['x-rapidapi-key'] != "SIGN_UP_FOR_KEY":
                try:
                    words_response = requests.get(
                        WORDS_API_URL.format(word=word),
                        headers=WORDS_API_HEADERS
                    )
                    
                    if words_response.status_code == 200:
                        words_data = words_response.json()
                        
                        if 'results' in words_data and words_data['results']:
                            for item in words_data['results']:
                                def_text = item.get('definition', '')
                                part_of_speech = item.get('partOfSpeech', '')
                                
                                # Only add appropriate definitions
                                if is_appropriate_definition(def_text):
                                    def_obj = {
                                        'definition': def_text,
                                        'part_of_speech': part_of_speech,
                                    }
                                    
                                    # Add example if available
                                    if 'examples' in item and item['examples']:
                                        example_text = item['examples'][0]
                                        if not profanity.contains_profanity(example_text):
                                            def_obj['example'] = example_text
                                            result['examples'].append(example_text)
                                    
                                    result['definitions'].append(def_obj)
                            
                            # Get synonyms
                            if 'synonyms' in words_data and words_data['synonyms']:
                                result['synonyms'].extend(words_data['synonyms'])
                            
                            # Get antonyms
                            if 'antonyms' in words_data and words_data['antonyms']:
                                result['antonyms'].extend(words_data['antonyms'])
                except Exception as e:
                    logger.error(f"Error fetching WordsAPI data: {str(e)}")
        
        # If no definitions found, try Urban Dictionary as a last resort
        # But filter out inappropriate content
        if not result['definitions']:
            try:
                urban_response = requests.get(URBAN_DICTIONARY_API_URL.format(word=word))
                if urban_response.status_code == 200:
                    urban_data = urban_response.json()
                    
                    if 'list' in urban_data and urban_data['list']:
                        # Filter and sort by thumbs up to get more reliable definitions
                        filtered_defs = []
                        
                        for item in urban_data['list']:
                            def_text = item.get('definition', '').replace('[', '').replace(']', '')
                            
                            # Only add appropriate definitions
                            if is_appropriate_definition(def_text):
                                filtered_defs.append(item)
                        
                        # Sort by thumbs up count to get more reliable definitions
                        filtered_defs.sort(key=lambda x: x.get('thumbs_up', 0), reverse=True)
                        
                        # Get top 3 definitions
                        for item in filtered_defs[:3]:
                            def_text = item.get('definition', '').replace('[', '').replace(']', '')
                            
                            def_obj = {
                                'definition': def_text,
                                'part_of_speech': 'slang',
                            }
                            
                            if item.get('example'):
                                example_text = item.get('example', '').replace('[', '').replace(']', '')
                                if not profanity.contains_profanity(example_text):
                                    def_obj['example'] = example_text
                                    result['examples'].append(example_text)
                            
                            result['definitions'].append(def_obj)
            except Exception as e:
                logger.error(f"Error fetching Urban Dictionary data: {str(e)}")
        
        # Translate the word if target language is not English
        if target_lang != 'en' and translator:
            try:
                # Translate the word
                translation = translator.translate(word, dest=target_lang)
                result['translation'] = translation.text
                result['source_language'] = translation.src
                
                # Generate pronunciation for the translation
                translation_audio = generate_pronunciation(translation.text, target_lang)
                if translation_audio:
                    result['translation_pronunciation'] = translation_audio
                
                # Get definitions and examples in target language
                # First, try to find definitions for the translated word in the target language
                if target_lang in ['es', 'fr', 'de', 'it', 'pt', 'ru']:  # Languages supported by Free Dictionary API
                    try:
                        target_dict_response = requests.get(DICTIONARY_API_URL.format(
                            lang=target_lang, 
                            word=result['translation']
                        ))
                        
                        if target_dict_response.status_code == 200:
                            target_dict_data = target_dict_response.json()
                            
                            if target_dict_data and len(target_dict_data) > 0:
                                entry = target_dict_data[0]
                                
                                # Get meanings in target language
                                if 'meanings' in entry:
                                    for meaning in entry['meanings']:
                                        part_of_speech = meaning.get('partOfSpeech', '')
                                        
                                        # Get definitions in target language
                                        if 'definitions' in meaning:
                                            clean_definitions = remove_bad_definitions(
                                                meaning['definitions'], 
                                                part_of_speech
                                            )
                                            result['translated_definitions'].extend(clean_definitions)
                                            
                                            # Add examples to the translated examples list
                                            for def_obj in clean_definitions:
                                                if 'example' in def_obj:
                                                    result['translated_examples'].append(def_obj['example'])
                    except Exception as e:
                        logger.error(f"Error fetching target language dictionary data: {str(e)}")
                
                # If no definitions found in target language, translate the English definitions
                if not result['translated_definitions'] and result['definitions']:
                    for definition in result['definitions']:
                        try:
                            # Translate the definition
                            translated_def = translator.translate(
                                definition['definition'], 
                                dest=target_lang
                            )
                            
                            # Add to translated definitions
                            result['translated_definitions'].append({
                                'definition': translated_def.text,
                                'part_of_speech': definition['part_of_speech']
                            })
                            
                            # Translate example if available
                            if 'example' in definition:
                                translated_example = translator.translate(
                                    definition['example'], 
                                    dest=target_lang
                                )
                                result['translated_examples'].append(translated_example.text)
                        except Exception as e:
                            logger.error(f"Error translating definition: {str(e)}")
                            continue
                
                # Translate some examples if none are found
                if not result['translated_examples'] and result['examples']:
                    examples_to_translate = result['examples'][:3]  # Translate up to 3 examples
                    for example in examples_to_translate:
                        try:
                            translated_example = translator.translate(example, dest=target_lang)
                            result['translated_examples'].append(translated_example.text)
                        except Exception as e:
                            logger.error(f"Error translating example: {str(e)}")
                            continue
            except Exception as e:
                logger.error(f"Error translating word: {str(e)}")
        
        # Generate pronunciation for the original word
        source_lang = result['source_language']
        audio_base64 = generate_pronunciation(word, source_lang)
        if audio_base64:
            result['pronunciation'] = audio_base64
        
        # Add to search history
        timestamp = datetime.now().isoformat()
        history_entry = {
            'word': word,
            'target_language': target_lang,
            'timestamp': timestamp,
            'has_definition': bool(result['definitions']),
            'has_translation': bool(result.get('translation'))
        }
        
        SEARCH_HISTORY.insert(0, history_entry)
        if len(SEARCH_HISTORY) > MAX_HISTORY_SIZE:
            SEARCH_HISTORY.pop()
        
        # Save result to cache
        save_to_cache(cache_key, result)
        
        return jsonify(result)
    
    except Exception as e:
        logger.error(f"Error in search_word: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/speech-to-text', methods=['POST'])
def speech_to_text():
    """Convert speech to text."""
    if 'audio' not in request.files:
        return jsonify({'error': 'No audio file provided'}), 400
    
    audio_file = request.files['audio']
    recognizer = sr.Recognizer()
    
    try:
        logger.info("Processing speech to text")
        # Create a unique filename to avoid conflicts
        unique_filename = f"temp_speech_{uuid.uuid4().hex}.wav"
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, unique_filename)
        
        audio_file.save(file_path)
        
        # Add a small delay to ensure file is fully written
        time.sleep(0.1)
        
        with sr.AudioFile(file_path) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data)
            
            # Clean up the file
            try:
                os.remove(file_path)
            except Exception as e:
                logger.warning(f"Could not remove temporary file {file_path}: {str(e)}")
                
            return jsonify({'text': text})
    
    except sr.UnknownValueError:
        return jsonify({'error': 'Could not understand audio'}), 400
    except sr.RequestError as e:
        logger.error(f"Speech recognition service error: {str(e)}")
        return jsonify({'error': 'Speech recognition service unavailable'}), 503
    except Exception as e:
        logger.error(f"Error in speech_to_text: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/pronounce', methods=['POST'])
def pronounce_word():
    """Generate pronunciation for a word in a specific language."""
    if not request.is_json:
        return jsonify({'error': 'Request must be JSON'}), 400
    
    data = request.json
    text = data.get('text')
    lang = data.get('lang', 'en')
    
    if not text:
        return jsonify({'error': 'Text is required'}), 400
    
    # Trim long text to a reasonable length for pronunciation
    if len(text) > 100:
        logger.warning(f"Text too long ({len(text)} chars), truncating for pronunciation")
        text = text[:100] + "..."
    
    # Check if language is supported
    if lang not in LANGUAGES:
        logger.warning(f"Unsupported language requested: {lang}")
        return jsonify({
            'error': f'Unsupported language: {lang}', 
            'supported_languages': list(LANGUAGES.keys())
        }), 400
    
    try:
        logger.info(f"Generating pronunciation for '{text[:20]}...' in {LANGUAGES[lang]}")
        audio_base64 = generate_pronunciation(text, lang)
        
        if audio_base64:
            return jsonify({
                'audio': audio_base64,
                'status': 'success',
                'language': lang,
                'text_length': len(text)
            })
        else:
            # Attempt fallback to English for non-English languages if appropriate
            if lang != 'en' and all(c.isascii() for c in text):
                logger.info(f"Attempting fallback to English pronunciation")
                audio_base64 = generate_pronunciation(text, 'en')
                if audio_base64:
                    return jsonify({
                        'audio': audio_base64,
                        'status': 'success_fallback',
                        'message': 'Used English pronunciation as fallback',
                        'original_language': lang,
                        'fallback_language': 'en'
                    })
            
            return jsonify({
                'error': 'Failed to generate pronunciation', 
                'language': lang,
                'text_length': len(text)
            }), 500
    except Exception as e:
        error_message = str(e)
        logger.error(f"Error in pronounce_word: {error_message}")
        return jsonify({
            'error': error_message,
            'status': 'error'
        }), 500

@app.route('/api/pronounce-batch', methods=['POST'])
def pronounce_batch():
    """Generate pronunciations for multiple words in specific languages."""
    if not request.is_json:
        return jsonify({'error': 'Request must be JSON'}), 400
    
    data = request.json
    items = data.get('items', [])
    
    if not items or not isinstance(items, list):
        return jsonify({'error': 'Items array is required'}), 400
    
    results = {}
    errors = []
    
    for item in items[:10]:  # Limit to 10 items per batch for performance
        text = item.get('text')
        lang = item.get('lang', 'en')
        item_id = item.get('id', str(uuid.uuid4()))
        
        if not text:
            errors.append({
                'id': item_id,
                'error': 'Text is required',
                'status': 'error'
            })
            continue
        
        # Trim long text
        if len(text) > 100:
            text = text[:100] + "..."
        
        # Check language support
        if lang not in LANGUAGES:
            errors.append({
                'id': item_id,
                'error': f'Unsupported language: {lang}',
                'status': 'error'
            })
            continue
        
        try:
            audio_base64 = generate_pronunciation(text, lang)
            
            if audio_base64:
                results[item_id] = {
                    'audio': audio_base64,
                    'status': 'success',
                    'language': lang
                }
            else:
                errors.append({
                    'id': item_id,
                    'error': 'Failed to generate pronunciation',
                    'status': 'error'
                })
                
        except Exception as e:
            logger.error(f"Error generating pronunciation for {item_id}: {str(e)}")
            errors.append({
                'id': item_id,
                'error': str(e),
                'status': 'error'
            })
    
    return jsonify({
        'results': results,
        'errors': errors,
        'status': 'complete',
        'success_count': len(results),
        'error_count': len(errors)
    })

@app.errorhandler(404)
def not_found(e):
    """Handle 404 errors."""
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def server_error(e):
    """Handle 500 errors."""
    return jsonify({'error': 'Server error'}), 500

# 6. Add a health check endpoint
@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'version': '1.1.0',
        'apis': {
            'translator': bool(translator),
            'dictionary': True,
            'tts': True
        },
        'uptime': 'unknown'  # In a production app, you'd track actual uptime
    })

if __name__ == '__main__':
    # Clear cache on startup
    CACHE = {}
    app.run(debug=True, port=8000) 