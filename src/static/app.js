/**
 * Who's That? - Frontend Application
 */

const app = {
    currentMode: 'look',
    isLoading: false,
    currentSubject: null,
    capturedFrame: null,
    capturedFrameData: null,
    speechRecognition: null,
    audioEnabled: true,
    videoStream: null,

    /**
     * Play audio from base64 MP3 data
     */
    playAudio(base64Audio) {
        if (!base64Audio || !this.audioEnabled) return;

        try {
            const audio = new Audio(`data:audio/mp3;base64,${base64Audio}`);
            audio.play().catch(err => {
                console.warn('Audio playback failed:', err);
            });
        } catch (err) {
            console.warn('Audio error:', err);
        }
    },

    /**
     * Initialize the browser camera
     */
    async initCamera() {
        try {
            // Request camera access - prefer back camera on mobile
            const constraints = {
                video: {
                    facingMode: { ideal: 'environment' },
                    width: { ideal: 1280 },
                    height: { ideal: 720 }
                },
                audio: false
            };

            this.videoStream = await navigator.mediaDevices.getUserMedia(constraints);
            const video = document.getElementById('camera-feed');
            video.srcObject = this.videoStream;
            console.log('Camera initialized');
        } catch (err) {
            console.error('Camera access failed:', err);
            alert('Could not access camera. Please allow camera permissions and reload.');
        }
    },

    /**
     * Capture current frame as base64 JPEG
     */
    captureFrame() {
        const video = document.getElementById('camera-feed');
        const canvas = document.getElementById('capture-canvas');
        const ctx = canvas.getContext('2d');

        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        ctx.drawImage(video, 0, 0);

        // Return base64 without the data URL prefix
        const dataUrl = canvas.toDataURL('image/jpeg', 0.85);
        return dataUrl.split(',')[1];
    },

    /**
     * Initialize the application
     */
    init() {
        // Initialize browser camera
        this.initCamera();

        // Load settings
        this.loadSettings();

        // Load library
        this.loadLibrary();

        // Set up speech recognition if available
        this.initSpeechRecognition();

        // Set up enter key handlers
        document.getElementById('name-input').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.saveEnroll();
        });
        document.getElementById('chat-input').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.sendChat();
        });

        // Volume slider
        document.getElementById('volume-slider').addEventListener('change', (e) => {
            this.setVolume(e.target.value);
        });

        console.log('Who\'s That? initialized');
    },

    /**
     * Switch between modes
     */
    switchMode(mode) {
        if (this.isLoading) return;

        this.currentMode = mode;

        // Update tabs
        document.querySelectorAll('.tab').forEach(tab => {
            tab.classList.toggle('active', tab.dataset.mode === mode);
        });

        // Update mode sections
        document.querySelectorAll('.mode').forEach(section => {
            section.classList.remove('active');
            section.classList.add('hidden');
        });
        document.getElementById(`${mode}-mode`).classList.remove('hidden');
        document.getElementById(`${mode}-mode`).classList.add('active');

        // Reset states
        this.showCameraFeed();
        this.hideOverlay();

        // Mode-specific setup
        if (mode === 'meet') {
            this.loadLibrary();
            this.resetEnrollUI();
        } else if (mode === 'who') {
            this.resetWhoUI();
        }
    },

    /**
     * Show loading overlay
     */
    showOverlay(text = 'Hmm, let me look closely...') {
        document.getElementById('thinking-text').textContent = text;
        document.getElementById('camera-overlay').classList.remove('hidden');
    },

    /**
     * Hide loading overlay
     */
    hideOverlay() {
        document.getElementById('camera-overlay').classList.add('hidden');
    },

    /**
     * Show camera feed
     */
    showCameraFeed() {
        document.getElementById('camera-feed').classList.remove('hidden');
        document.getElementById('frozen-frame').classList.add('hidden');
    },

    /**
     * Freeze camera on captured frame
     */
    freezeFrame(imageUrl) {
        const frozenFrame = document.getElementById('frozen-frame');
        frozenFrame.src = imageUrl;
        frozenFrame.classList.remove('hidden');
        document.getElementById('camera-feed').classList.add('hidden');
    },

    /**
     * Set button loading state
     */
    setLoading(loading) {
        this.isLoading = loading;
        document.querySelectorAll('.action-btn.primary').forEach(btn => {
            btn.disabled = loading;
        });
    },

    // ==================== Look Mode ====================

    /**
     * Describe the current scene
     */
    async describeScene() {
        if (this.isLoading) return;

        this.setLoading(true);
        this.showOverlay('Let me see what\'s here...');

        try {
            const frame = this.captureFrame();
            const response = await fetch('/describe', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ frame })
            });
            const data = await response.json();

            if (data.error) {
                this.showResponse('look-response', data.error, true);
            } else {
                this.showResponse('look-response', data.description);
                this.playAudio(data.audio);
            }
        } catch (error) {
            this.showResponse('look-response', 'Oops! Something went wrong. Try again?', true);
        }

        this.hideOverlay();
        this.setLoading(false);
    },

    /**
     * Show a response in a response box
     */
    showResponse(elementId, text, isError = false) {
        const box = document.getElementById(elementId);
        box.textContent = text;
        box.classList.remove('hidden', 'error');
        if (isError) box.classList.add('error');
    },

    // ==================== Meet Mode ====================

    /**
     * Capture frame for enrollment
     */
    async captureForEnroll() {
        if (this.isLoading) return;

        this.setLoading(true);

        try {
            // Capture from browser camera
            this.capturedFrameData = this.captureFrame();
            const imageUrl = `data:image/jpeg;base64,${this.capturedFrameData}`;
            this.capturedFrame = imageUrl;
            this.freezeFrame(imageUrl);

            // Show enrollment UI
            document.getElementById('meet-capture').classList.add('hidden');
            document.getElementById('meet-enroll').classList.remove('hidden');
            document.getElementById('name-input').focus();
        } catch (error) {
            console.error('Capture failed:', error);
        }

        this.setLoading(false);
    },

    /**
     * Cancel enrollment
     */
    cancelEnroll() {
        this.resetEnrollUI();
        this.showCameraFeed();
    },

    /**
     * Save enrollment
     */
    async saveEnroll() {
        const nameInput = document.getElementById('name-input');
        const name = nameInput.value.trim();

        if (!name) {
            nameInput.focus();
            return;
        }

        this.setLoading(true);
        this.showOverlay('Saving...');

        try {
            const response = await fetch('/enroll', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, frame: this.capturedFrameData })
            });
            const data = await response.json();

            if (data.success) {
                this.playAudio(data.audio);
                this.resetEnrollUI();
                this.showCameraFeed();
                this.loadLibrary();
            } else {
                alert(data.error || 'Failed to save');
            }
        } catch (error) {
            alert('Failed to save. Try again?');
        }

        this.hideOverlay();
        this.setLoading(false);
    },

    /**
     * Reset enrollment UI
     */
    resetEnrollUI() {
        document.getElementById('meet-capture').classList.remove('hidden');
        document.getElementById('meet-enroll').classList.add('hidden');
        document.getElementById('name-input').value = '';
        this.capturedFrame = null;
        this.capturedFrameData = null;
    },

    /**
     * Load library of enrolled subjects
     */
    async loadLibrary() {
        try {
            const response = await fetch('/library');
            const data = await response.json();

            const grid = document.getElementById('subjects-grid');
            grid.innerHTML = '';

            if (data.subjects.length === 0) {
                grid.innerHTML = '<p style="color: #6c757d; text-align: center; grid-column: 1/-1;">No friends yet! Capture some photos to get started.</p>';
                return;
            }

            data.subjects.forEach(subject => {
                const card = document.createElement('div');
                card.className = 'subject-card';
                card.onclick = () => this.openSubjectModal(subject);
                card.innerHTML = `
                    <img src="/library/${subject.name}/thumbnail?size=160" alt="${subject.display_name}">
                    <span class="name">${subject.display_name}</span>
                    <span class="count">${subject.photo_count} photo${subject.photo_count > 1 ? 's' : ''}</span>
                `;
                grid.appendChild(card);
            });
        } catch (error) {
            console.error('Failed to load library:', error);
        }
    },

    /**
     * Open subject detail modal
     */
    openSubjectModal(subject) {
        this.currentSubject = subject;

        document.getElementById('modal-subject-name').textContent = subject.display_name;

        const photosContainer = document.getElementById('modal-photos');
        photosContainer.innerHTML = '';

        subject.photos.forEach(photo => {
            const img = document.createElement('img');
            img.src = `/library/${subject.name}/photo/${photo}`;
            img.alt = photo;
            img.onclick = () => this.deletePhoto(subject.name, photo);
            photosContainer.appendChild(img);
        });

        document.getElementById('subject-modal').classList.remove('hidden');
    },

    /**
     * Close subject modal
     */
    closeSubjectModal() {
        document.getElementById('subject-modal').classList.add('hidden');
        this.currentSubject = null;
    },

    /**
     * Add another photo to current subject
     */
    addPhotoToSubject() {
        if (!this.currentSubject) return;

        // Pre-fill the name and switch to capture mode
        this.closeSubjectModal();
        document.getElementById('name-input').value = this.currentSubject.display_name;
        this.captureForEnroll();
    },

    /**
     * Forget (delete) a subject
     */
    async forgetSubject() {
        if (!this.currentSubject) return;

        if (!confirm(`Are you sure you want to forget ${this.currentSubject.display_name}?`)) {
            return;
        }

        try {
            const response = await fetch(`/library/${this.currentSubject.name}`, {
                method: 'DELETE'
            });
            const data = await response.json();

            if (data.success) {
                this.playAudio(data.audio);
                this.closeSubjectModal();
                this.loadLibrary();
            } else {
                alert(data.message || 'Failed to delete');
            }
        } catch (error) {
            alert('Failed to delete. Try again?');
        }
    },

    /**
     * Delete a single photo
     */
    async deletePhoto(name, photoId) {
        if (!confirm('Delete this photo?')) return;

        try {
            const response = await fetch(`/library/${name}/${photoId}`, {
                method: 'DELETE'
            });
            const data = await response.json();

            if (data.success) {
                this.loadLibrary();
                // Refresh modal if still open
                if (this.currentSubject) {
                    const updatedResponse = await fetch('/library');
                    const updatedData = await updatedResponse.json();
                    const updatedSubject = updatedData.subjects.find(s => s.name === name);
                    if (updatedSubject) {
                        this.openSubjectModal(updatedSubject);
                    } else {
                        this.closeSubjectModal();
                    }
                }
            }
        } catch (error) {
            alert('Failed to delete photo');
        }
    },

    // ==================== Who Mode ====================

    /**
     * Identify subjects in current frame
     */
    async identifySubjects() {
        if (this.isLoading) return;

        this.setLoading(true);
        this.showOverlay('Let me see who\'s there...');

        try {
            const frame = this.captureFrame();
            const response = await fetch('/identify', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ frame })
            });
            const data = await response.json();

            if (data.redirect_to_meet) {
                this.switchMode('meet');
                alert(data.error);
            } else if (data.error) {
                this.showResponse('who-response', data.error, true);
            } else {
                this.showResponse('who-response', data.response);
                this.playAudio(data.audio);
                document.getElementById('chat-section').classList.remove('hidden');
            }
        } catch (error) {
            this.showResponse('who-response', 'Oops! Something went wrong. Try again?', true);
        }

        this.hideOverlay();
        this.setLoading(false);
    },

    /**
     * Send chat follow-up
     */
    async sendChat() {
        const input = document.getElementById('chat-input');
        const message = input.value.trim();

        if (!message || this.isLoading) return;

        this.setLoading(true);
        this.showOverlay('Thinking...');

        try {
            const response = await fetch('/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message })
            });
            const data = await response.json();

            if (data.error) {
                this.showResponse('who-response', data.error, true);
            } else {
                // Append to response
                const box = document.getElementById('who-response');
                box.textContent += '\n\nYou: ' + message + '\n\n' + data.response;
                this.playAudio(data.audio);
            }

            input.value = '';
        } catch (error) {
            this.showResponse('who-response', 'Failed to send message. Try again?', true);
        }

        this.hideOverlay();
        this.setLoading(false);
    },

    /**
     * Start a new photo (reset who mode)
     */
    async newPhoto() {
        try {
            await fetch('/chat/reset', { method: 'POST' });
        } catch (error) {
            // Ignore reset errors
        }

        this.resetWhoUI();
    },

    /**
     * Reset Who mode UI
     */
    resetWhoUI() {
        document.getElementById('who-response').classList.add('hidden');
        document.getElementById('chat-section').classList.add('hidden');
        document.getElementById('chat-input').value = '';
    },

    // ==================== Settings ====================

    /**
     * Toggle settings panel
     */
    toggleSettings() {
        document.getElementById('settings-panel').classList.toggle('hidden');
    },

    /**
     * Load settings from server
     */
    async loadSettings() {
        try {
            const response = await fetch('/settings');
            const data = await response.json();

            document.getElementById('camera-url').value = data.camera_url_override || '';
            document.getElementById('vlm-url').value = data.vlm_url || '';
        } catch (error) {
            console.error('Failed to load settings:', error);
        }
    },

    /**
     * Set TTS volume
     */
    async setVolume(volume) {
        try {
            await fetch('/tts/volume', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ volume: parseFloat(volume) })
            });
        } catch (error) {
            console.error('Failed to set volume:', error);
        }
    },

    /**
     * Clear all photos
     */
    async clearAllPhotos() {
        if (!confirm('Are you sure you want to delete ALL enrolled photos? This cannot be undone!')) {
            return;
        }

        if (!confirm('Really delete everything?')) {
            return;
        }

        try {
            const response = await fetch('/library/clear', { method: 'POST' });
            const data = await response.json();

            if (data.success) {
                alert(data.message);
                this.loadLibrary();
                this.toggleSettings();
            }
        } catch (error) {
            alert('Failed to clear photos');
        }
    },

    // ==================== Speech Recognition ====================

    /**
     * Initialize Web Speech API
     */
    initSpeechRecognition() {
        if ('webkitSpeechRecognition' in window) {
            this.speechRecognition = new webkitSpeechRecognition();
            this.speechRecognition.continuous = false;
            this.speechRecognition.interimResults = false;
            this.speechRecognition.lang = 'en-US';

            this.speechRecognition.onresult = (event) => {
                const transcript = event.results[0][0].transcript;
                if (this.currentSpeechInput) {
                    document.getElementById(this.currentSpeechInput).value = transcript;
                }
            };

            this.speechRecognition.onend = () => {
                document.querySelectorAll('.mic-btn').forEach(btn => {
                    btn.classList.remove('listening');
                });
            };

            this.speechRecognition.onerror = (event) => {
                console.error('Speech recognition error:', event.error);
                document.querySelectorAll('.mic-btn').forEach(btn => {
                    btn.classList.remove('listening');
                });
            };
        }
    },

    /**
     * Start speech input for a text field
     */
    startSpeechInput(inputId) {
        if (!this.speechRecognition) {
            alert('Speech recognition is not supported in this browser');
            return;
        }

        this.currentSpeechInput = inputId;

        // Visual feedback
        const input = document.getElementById(inputId);
        const micBtn = input.parentElement.querySelector('.mic-btn');
        micBtn.classList.add('listening');

        this.speechRecognition.start();
    }
};

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => app.init());
