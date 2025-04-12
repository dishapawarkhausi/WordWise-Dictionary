document.addEventListener('DOMContentLoaded', function() {
    const searchForm = document.getElementById('search-form');
    const wordInput = document.getElementById('word-input');
    const languageSelect = document.getElementById('language-select');
    const resultsContainer = document.getElementById('results-container');
    const loadingIndicator = document.getElementById('loading-indicator');
    const micButton = document.getElementById('mic-button');
    const historyList = document.getElementById('history-list');
    const clearHistoryBtn = document.getElementById('clear-history-btn');
    
    // Fetch and populate languages dropdown
    async function loadLanguages() {
        try {
            const response = await fetch('/api/languages');
            const languages = await response.json();
            
            // Clear existing options except the first one (English)
            while (languageSelect.options.length > 1) {
                languageSelect.remove(1);
            }
            
            for (const [code, name] of Object.entries(languages)) {
                if (code === 'en') continue; // Skip English as it's already added
                const option = document.createElement('option');
                option.value = code;
                option.textContent = name;
                languageSelect.appendChild(option);
            }
        } catch (error) {
            console.error('Failed to load languages:', error);
        }
    }
    
    // Load search history
    async function loadHistory() {
        try {
            const response = await fetch('/api/history');
            const history = await response.json();
            
            historyList.innerHTML = '';
            
            if (history.length === 0) {
                historyList.innerHTML = '<li class="no-history">No search history</li>';
                return;
            }
            
            history.forEach(item => {
                const li = document.createElement('li');
                li.className = 'history-item';
                li.innerHTML = `
                    <span class="history-word">${item.word}</span>
                    <span class="history-lang">${item.target_language}</span>
                    <span class="history-time">${new Date(item.timestamp).toLocaleTimeString()}</span>
                `;
                li.addEventListener('click', () => {
                    wordInput.value = item.word;
                    languageSelect.value = item.target_language;
                    searchWord(item.word, item.target_language);
                });
                historyList.appendChild(li);
            });
        } catch (error) {
            console.error('Failed to load history:', error);
        }
    }
    
    // Search for a word
    async function searchWord(word, targetLang) {
        loadingIndicator.classList.remove('hidden');
        resultsContainer.innerHTML = '';
        
        try {
            const response = await fetch('/api/search', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    word: word,
                    target_lang: targetLang
                })
            });
            
            const data = await response.json();
            
            if (response.ok) {
                displayResults(data);
                loadHistory(); // Refresh history after successful search
            } else {
                displayError(data.error || 'An error occurred');
            }
        } catch (error) {
            displayError('Network error. Please try again.');
            console.error('Search error:', error);
        } finally {
            loadingIndicator.classList.add('hidden');
        }
    }
    
    // Display search results
    function displayResults(data) {
        const resultCard = document.createElement('div');
        resultCard.className = 'result-card';
        
        // Create word title with pronunciation button
        const wordTitle = document.createElement('div');
        wordTitle.className = 'word-title';
        wordTitle.textContent = data.word;
        
        // Add pronunciation button if available
        if (data.pronunciation) {
            const pronounceBtn = document.createElement('button');
            pronounceBtn.className = 'btn-icon';
            pronounceBtn.innerHTML = '<i class="fas fa-volume-up"></i>';
            pronounceBtn.addEventListener('click', () => {
                playAudio(data.pronunciation);
            });
            wordTitle.appendChild(pronounceBtn);
        }
        
        resultCard.appendChild(wordTitle);
        
        // Add phonetics if available
        if (data.phonetics && data.phonetics.length > 0) {
            const phonetics = document.createElement('div');
            phonetics.className = 'phonetics';
            phonetics.textContent = data.phonetics.map(p => p.text).join(', ');
            resultCard.appendChild(phonetics);
        }
        
        // Add translation if available
        if (data.translation) {
            const translation = document.createElement('div');
            translation.className = 'translation';
            
            const translationText = document.createElement('span');
            translationText.textContent = data.translation;
            translation.appendChild(translationText);
            
            // Add translation pronunciation button if available
            if (data.translation_pronunciation) {
                const translatePronounceBtn = document.createElement('button');
                translatePronounceBtn.className = 'btn-icon';
                translatePronounceBtn.innerHTML = '<i class="fas fa-volume-up"></i>';
                translatePronounceBtn.addEventListener('click', () => {
                    playAudio(data.translation_pronunciation);
                });
                translation.appendChild(translatePronounceBtn);
            }
            
            resultCard.appendChild(translation);
        }
        
        // Add definitions section
        if (data.definitions && data.definitions.length > 0) {
            const definitionsSection = document.createElement('div');
            definitionsSection.className = 'definitions-section';
            
            const definitionsTitle = document.createElement('h3');
            definitionsTitle.textContent = 'Definitions';
            definitionsSection.appendChild(definitionsTitle);
            
            const definitionsList = document.createElement('ul');
            definitionsList.className = 'definitions-list';
            
            data.definitions.forEach(def => {
                const li = document.createElement('li');
                li.innerHTML = `
                    <span class="part-of-speech">${def.part_of_speech}</span>
                    <p class="definition">${def.definition}</p>
                    ${def.example ? `<p class="example">"${def.example}"</p>` : ''}
                `;
                definitionsList.appendChild(li);
            });
            
            definitionsSection.appendChild(definitionsList);
            resultCard.appendChild(definitionsSection);
        }
        
        // Add translated definitions if available
        if (data.translated_definitions && data.translated_definitions.length > 0) {
            const translatedSection = document.createElement('div');
            translatedSection.className = 'translated-section';
            
            const translatedTitle = document.createElement('h3');
            translatedTitle.textContent = `Definitions in ${LANGUAGES[data.target_language]}`;
            translatedSection.appendChild(translatedTitle);
            
            const translatedList = document.createElement('ul');
            translatedList.className = 'definitions-list';
            
            data.translated_definitions.forEach(def => {
                const li = document.createElement('li');
                li.innerHTML = `
                    <span class="part-of-speech">${def.part_of_speech}</span>
                    <p class="definition">${def.definition}</p>
                    ${def.example ? `<p class="example">"${def.example}"</p>` : ''}
                `;
                translatedList.appendChild(li);
            });
            
            translatedSection.appendChild(translatedList);
            resultCard.appendChild(translatedSection);
        }
        
        // Add synonyms & antonyms if available
        if ((data.synonyms && data.synonyms.length > 0) || (data.antonyms && data.antonyms.length > 0)) {
            const relatedSection = document.createElement('div');
            relatedSection.className = 'related-section';
            
            if (data.synonyms && data.synonyms.length > 0) {
                const synonymsDiv = document.createElement('div');
                synonymsDiv.className = 'synonyms';
                
                const synonymsTitle = document.createElement('h4');
                synonymsTitle.textContent = 'Synonyms:';
                synonymsDiv.appendChild(synonymsTitle);
                
                const synonymsList = document.createElement('div');
                synonymsList.className = 'word-list';
                
                data.synonyms.slice(0, 10).forEach(word => {
                    const chip = document.createElement('span');
                    chip.className = 'word-chip';
                    chip.textContent = word;
                    chip.addEventListener('click', () => {
                        wordInput.value = word;
                        searchWord(word, languageSelect.value);
                    });
                    synonymsList.appendChild(chip);
                });
                
                synonymsDiv.appendChild(synonymsList);
                relatedSection.appendChild(synonymsDiv);
            }
            
            if (data.antonyms && data.antonyms.length > 0) {
                const antonymsDiv = document.createElement('div');
                antonymsDiv.className = 'antonyms';
                
                const antonymsTitle = document.createElement('h4');
                antonymsTitle.textContent = 'Antonyms:';
                antonymsDiv.appendChild(antonymsTitle);
                
                const antonymsList = document.createElement('div');
                antonymsList.className = 'word-list';
                
                data.antonyms.slice(0, 10).forEach(word => {
                    const chip = document.createElement('span');
                    chip.className = 'word-chip';
                    chip.textContent = word;
                    chip.addEventListener('click', () => {
                        wordInput.value = word;
                        searchWord(word, languageSelect.value);
                    });
                    antonymsList.appendChild(chip);
                });
                
                antonymsDiv.appendChild(antonymsList);
                relatedSection.appendChild(antonymsDiv);
            }
            
            resultCard.appendChild(relatedSection);
        }
        
        resultsContainer.appendChild(resultCard);
    }
    
    // Display error message
    function displayError(message) {
        const errorDiv = document.createElement('div');
        errorDiv.className = 'error-message';
        errorDiv.textContent = message;
        resultsContainer.appendChild(errorDiv);
    }
    
    // Play audio from base64 data
    function playAudio(base64Audio) {
        const audio = new Audio(`data:audio/mp3;base64,${base64Audio}`);
        audio.play().catch(error => console.error('Audio playback error:', error));
    }
    
    // Speech recognition for mic button
    let isRecording = false;
    
    function toggleSpeechRecognition() {
        if (!('webkitSpeechRecognition' in window)) {
            alert('Speech recognition is not supported in your browser.');
            return;
        }
        
        if (isRecording) {
            // Stop recording logic would be here
            micButton.classList.remove('recording');
            isRecording = false;
            return;
        }
        
        const recognition = new webkitSpeechRecognition();
        recognition.continuous = false;
        recognition.interimResults = false;
        
        recognition.onstart = function() {
            micButton.classList.add('recording');
            isRecording = true;
        };
        
        recognition.onresult = function(event) {
            const transcript = event.results[0][0].transcript;
            wordInput.value = transcript;
        };
        
        recognition.onerror = function(event) {
            console.error('Speech recognition error:', event.error);
            micButton.classList.remove('recording');
            isRecording = false;
        };
        
        recognition.onend = function() {
            micButton.classList.remove('recording');
            isRecording = false;
        };
        
        recognition.start();
    }
    
    // Event listeners
    searchForm.addEventListener('submit', function(e) {
        e.preventDefault();
        const word = wordInput.value.trim();
        const targetLang = languageSelect.value;
        
        if (word) {
            searchWord(word, targetLang);
        }
    });
    
    micButton.addEventListener('click', toggleSpeechRecognition);
    
    clearHistoryBtn.addEventListener('click', async function() {
        try {
            await fetch('/api/clear-history', { method: 'POST' });
            loadHistory();
        } catch (error) {
            console.error('Failed to clear history:', error);
        }
    });
    
    // Initialize
    loadLanguages();
    loadHistory();
    
    // Global variable for languages
    window.LANGUAGES = {};
    
    // Fetch languages for global use
    (async function() {
        try {
            const response = await fetch('/api/languages');
            window.LANGUAGES = await response.json();
        } catch (error) {
            console.error('Failed to load languages globally:', error);
        }
    })();
}); 