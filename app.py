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
    try:
        # Create a unique filename to avoid conflicts
        unique_filename = f"temp_audio_{uuid.uuid4().hex}.mp3"
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, unique_filename)
        
        # Generate the audio file
        tts = gTTS(text=text, lang=lang)
        tts.save(file_path)
        
        # Add a small delay to ensure file is fully written
        time.sleep(0.1)
        
        # Read the file and convert to base64
        with open(file_path, 'rb') as audio_file:
            audio_base64 = base64.b64encode(audio_file.read()).decode('utf-8')
        
        # Clean up the file
        try:
            os.remove(file_path)
        except Exception as e:
            logger.warning(f"Could not remove temporary file {file_path}: {str(e)}")
        
        return audio_base64
    except Exception as e:
        logger.error(f"Failed to generate pronunciation: {str(e)}")
        return None

@app.route('/api/search', methods=['POST'])
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
            'translation_pronunciation': None
        }
        
        # Get dictionary definition (only for English currently)
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
                translation = translator.translate(word, dest=target_lang)
                result['translation'] = translation.text
                result['source_language'] = translation.src
                
                # Generate pronunciation for the translation
                translation_audio = generate_pronunciation(translation.text, target_lang)
                if translation_audio:
                    result['translation_pronunciation'] = translation_audio
            except Exception as e:
                logger.error(f"Error translating word: {str(e)}")
        
        # Generate pronunciation for the original word
        source_lang = result['source_language']
        audio_base64 = generate_pronunciation(word, source_lang)
        if audio_base64:
            result['pronunciation'] = audio_base64
        
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
    
    if lang not in LANGUAGES:
        return jsonify({'error': f'Unsupported language: {lang}'}), 400
    
    try:
        audio_base64 = generate_pronunciation(text, lang)
        if audio_base64:
            return jsonify({'audio': audio_base64})
        else:
            return jsonify({'error': 'Failed to generate pronunciation'}), 500
    except Exception as e:
        logger.error(f"Error in pronounce_word: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.errorhandler(404)
def not_found(e):
    """Handle 404 errors."""
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def server_error(e):
    """Handle 500 errors."""
    return jsonify({'error': 'Server error'}), 500

if __name__ == '__main__':
    app.run(debug=True) 