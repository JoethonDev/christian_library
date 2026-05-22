//  Shared chunked uploader utility
//    Provides a small browser-side helper to initialize a chunked upload session
//    and stream file slices to the server with minimal memory overhead.

//    Usage:
//      const uploader = new ChunkedUploader({ initUrl, chunkUrl, csrfToken, chunkSize });
//      await uploader.uploadFile(file, metadata, {
//          onProgress: (offset, total) => { /* update UI */ },
//          onFinal: (lastResp) => { /* final server response */ },
//          onError: (err) => { /* handle error */ }
//      });

//    This file intentionally does not depend on any framework and exposes
//    `window.ChunkedUploader` as a global class.


(function (global) {
    class ChunkedUploader {
        constructor({ initUrl, chunkUrl, csrfToken, chunkSize } = {}) {
            if (!initUrl || !chunkUrl) throw new Error('initUrl and chunkUrl are required');
            this.initUrl = initUrl;
            this.chunkUrl = chunkUrl;
            this.csrfToken = csrfToken || '';
            this.chunkSize = chunkSize || (95 * 1024 * 1024); // 95 MB default
        }

        async initSession(payload) {
            const resp = await fetch(this.initUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken,
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify(payload),
                credentials: 'same-origin'
            });
            const data = await resp.json();
            if (!resp.ok || !data.success) {
                const err = new Error(data.error || 'Failed to initialize upload session');
                err.response = data;
                throw err;
            }
            return data;
        }

        async uploadChunks(file, sessionId, onProgress) {
            let offset = 0;
            let lastResponse = null;

            while (offset < file.size) {
                const end = Math.min(offset + this.chunkSize, file.size);
                const chunk = file.slice(offset, end);

                const fd = new FormData();
                fd.append('session_id', sessionId);
                fd.append('chunk', chunk, file.name);
                // include CSRF in form for compatibility
                if (this.csrfToken) fd.append('csrfmiddlewaretoken', this.csrfToken);

                const resp = await fetch(this.chunkUrl, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': this.csrfToken,
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: fd,
                    credentials: 'same-origin'
                });

                const data = await resp.json();
                if (!resp.ok || !data.success) {
                    const err = new Error(data.error || 'Chunk upload failed');
                    err.response = data;
                    throw err;
                }

                lastResponse = data;
                offset = data.offset || offset + chunk.size;

                if (typeof onProgress === 'function') {
                    try { onProgress(offset, file.size); } catch (e) { /* ignore UI errors */ }
                }
            }

            return lastResponse;
        }

        async uploadFile(file, payload = {}, callbacks = {}) {
            const initData = await this.initSession(payload);
            const sessionId = initData.session_id;

            try {
                const lastResp = await this.uploadChunks(file, sessionId, callbacks.onProgress);
                if (callbacks.onFinal && typeof callbacks.onFinal === 'function') callbacks.onFinal(lastResp);
                return { sessionId, initData, lastResp };
            } catch (err) {
                if (callbacks.onError && typeof callbacks.onError === 'function') callbacks.onError(err);
                throw err;
            }
        }
    }

    global.ChunkedUploader = ChunkedUploader;
})(window);
