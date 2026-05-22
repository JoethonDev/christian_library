(function () {
    const fileInput = document.getElementById('bulk-file-input');
    const fileRows = document.getElementById('bulk-file-rows');
    const emptyRow = document.getElementById('bulk-empty-row');
    const submitButton = document.getElementById('bulk-upload-submit');
    const clearButton = document.getElementById('bulk-clear-selection');
    const initUrl = document.getElementById('bulk-upload-init-url').value;
    const chunkUrl = document.getElementById('bulk-upload-chunk-url').value;
    const statusUrl = document.getElementById('bulk-status-url').value;
    const tagsInput = document.getElementById('bulk-tags');
    const alertBox = document.getElementById('bulk-upload-alert');
    const progressList = document.getElementById('bulk-progress-list');
    const progressSummary = document.getElementById('bulk-progress-summary');
    const selectedCount = document.getElementById('bulk-selected-count');
    const typeSummary = document.getElementById('bulk-type-summary');
    const csrfToken = document.querySelector('input[name="csrfmiddlewaretoken"]').value;

    // Shared chunked uploader instance
    const uploader = new ChunkedUploader({ initUrl, chunkUrl, csrfToken, chunkSize: 95 * 1024 * 1024 });

    const state = {
        entries: [],
        progressMap: new Map(),
        pollTimer: null,
    };

    function showAlert(message, kind = 'info') {
        alertBox.className = `alert alert-${kind} border-0 rounded-3`;
        alertBox.textContent = message;
        alertBox.classList.remove('d-none');
    }

    function hideAlert() {
        alertBox.classList.add('d-none');
        alertBox.textContent = '';
    }

    function fileTypeFromName(name) {
        const extension = name.split('.').pop().toLowerCase();
        if (['mp4', 'avi', 'mov', 'wmv'].includes(extension)) return 'video';
        if (['mp3', 'wav', 'm4a'].includes(extension)) return 'audio';
        if (extension === 'pdf') return 'pdf';
        return 'unsupported';
    }

    function isSupportedFile(file) {
        return fileTypeFromName(file.name) !== 'unsupported';
    }

    function cleanedTitle(name) {
        return name.replace(/\.[^.]+$/, '').replace(/[\-_]+/g, ' ').trim();
    }

    function typeLabel(type) {
        switch (type) {
            case 'video': return 'Video';
            case 'audio': return 'Audio';
            case 'pdf': return 'PDF';
            default: return 'File';
        }
    }

    function typeBadgeClass(type) {
        switch (type) {
            case 'video': return 'text-bg-primary';
            case 'audio': return 'text-bg-success';
            case 'pdf': return 'text-bg-danger';
            default: return 'text-bg-secondary';
        }
    }

    function statusBadgeClass(status) {
        switch (status) {
            case 'completed': return 'text-bg-success';
            case 'failed': return 'text-bg-danger';
            case 'processing': return 'text-bg-warning';
            case 'pending': return 'text-bg-secondary';
            default: return 'text-bg-light';
        }
    }

    function renderFileRows() {
        if (state.entries.length === 0) {
            fileRows.innerHTML = `
                <tr id="bulk-empty-row">
                    <td colspan="5">
                        <div class="bulk-upload-empty">
                            <div class="bulk-upload-empty__icon">
                                <svg class="bi" aria-hidden="true" focusable="false"><use href="#bi-folder2-open"/></svg>
                            </div>
                            <h4 class="h5 fw-bold mb-2">No files selected yet.</h4>
                            <p class="text-muted mb-0">Choose a batch to start building the upload queue.</p>
                        </div>
                    </td>
                </tr>
            `;
            updateDashboardSummary();
            return;
        }

        fileRows.innerHTML = state.entries.map((entry, index) => `
            <tr data-entry-index="${index}">
                <td data-label="Type">
                    <span class="badge rounded-pill ${typeBadgeClass(entry.type)}">${typeLabel(entry.type)}</span>
                </td>
                <td data-label="File">
                    <div class="fw-semibold">${escapeHtml(entry.file.name)}</div>
                    <div class="text-muted small">${formatFileSize(entry.file.size)}</div>
                </td>
                <td data-label="Arabic Title">
                    <input type="text" class="form-control form-control-sm rounded-3 title-ar-input" value="${escapeAttribute(entry.titleAr)}" dir="rtl" placeholder="Arabic title">
                </td>
                <td data-label="English Title">
                    <input type="text" class="form-control form-control-sm rounded-3 title-en-input" value="${escapeAttribute(entry.titleEn)}" placeholder="English title">
                </td>
                <td data-label="Actions" class="text-end">
                    <button type="button" class="btn btn-sm btn-outline-danger rounded-pill remove-entry-btn">Remove</button>
                </td>
            </tr>
        `).join('');

        fileRows.querySelectorAll('tr[data-entry-index]').forEach((row) => {
            const index = Number(row.dataset.entryIndex);
            const entry = state.entries[index];
            const titleArInput = row.querySelector('.title-ar-input');
            const titleEnInput = row.querySelector('.title-en-input');
            const removeButton = row.querySelector('.remove-entry-btn');

            titleArInput.addEventListener('input', (event) => {
                entry.titleAr = event.target.value;
            });
            titleEnInput.addEventListener('input', (event) => {
                entry.titleEn = event.target.value;
            });
            removeButton.addEventListener('click', () => removeEntry(index));
        });

        updateDashboardSummary();
    }

    function renderProgressList() {
        if (state.progressMap.size === 0) {
            progressList.innerHTML = `
                <div class="list-group-item border-0">
                    <div class="bulk-upload-progress__empty">
                        <div class="bulk-upload-progress__empty-icon">
                            <svg class="bi" aria-hidden="true" focusable="false"><use href="#bi-hourglass-split"/></svg>
                        </div>
                        <h4 class="h6 fw-bold mb-1" dir="ltr">Upload files to see progress here.</h4>
                        <p class="small text-muted mb-0" dir="ltr">Each queued item will appear here with live processing updates.</p>
                    </div>
                </div>
            `;
            progressSummary.classList.add('d-none');
            progressSummary.innerHTML = '';
            return;
        }

        const rows = Array.from(state.progressMap.values());
        progressList.innerHTML = rows.map((row) => `
            <div class="list-group-item d-flex align-items-start justify-content-between gap-3 py-3" data-progress-id="${row.contentId || row.key}">
                <div class="flex-grow-1 min-w-0">
                    <div class="d-flex align-items-center gap-2 mb-1">
                        <span class="badge rounded-pill ${typeBadgeClass(row.type)}">${typeLabel(row.type)}</span>
                        <span class="fw-semibold text-truncate" dir="ltr">${escapeHtml(row.name)}</span>
                    </div>
                    <div class="small text-muted text-truncate" dir="ltr">${escapeHtml(row.message)}</div>
                </div>
                <div class="text-end">
                    <span class="badge rounded-pill ${statusBadgeClass(row.status)}">${escapeHtml(row.statusLabel)}</span>
                </div>
            </div>
        `).join('');

        const completed = rows.filter((row) => ['completed', 'failed'].includes(row.status)).length;
        progressSummary.classList.remove('d-none');
        progressSummary.innerHTML = `
                <div class="alert alert-light border rounded-3 mb-0 py-2 small" dir="ltr">
                <strong>${completed}</strong> / <strong>${rows.length}</strong> items finished.
            </div>
        `;
    }

    function addFiles(files) {
        const accepted = [];
        Array.from(files).forEach((file) => {
            const type = fileTypeFromName(file.name);
            if (type === 'unsupported') {
                showAlert(`${file.name} is not a supported file type.`, 'warning');
                return;
            }

            accepted.push({
                file,
                type,
                titleAr: cleanedTitle(file.name),
                titleEn: '',
            });
        });

        if (accepted.length) {
            state.entries = state.entries.concat(accepted);
            hideAlert();
            renderFileRows();
            updateSubmitState();
        }
    }

    function updateDashboardSummary() {
        if (selectedCount) {
            selectedCount.textContent = String(state.entries.length);
        }

        if (typeSummary) {
            if (state.entries.length === 0) {
                typeSummary.textContent = '0 items';
                return;
            }

            const counts = state.entries.reduce((accumulator, entry) => {
                accumulator[entry.type] = (accumulator[entry.type] || 0) + 1;
                return accumulator;
            }, {});

            const labels = [
                counts.video ? `${counts.video} video${counts.video > 1 ? 's' : ''}` : null,
                counts.audio ? `${counts.audio} audio${counts.audio > 1 ? 's' : ''}` : null,
                counts.pdf ? `${counts.pdf} PDF${counts.pdf > 1 ? 's' : ''}` : null,
            ].filter(Boolean);

            typeSummary.textContent = labels.length ? labels.join(' · ') : `${state.entries.length} items`;
        }

        if (clearButton) {
            clearButton.disabled = state.entries.length === 0;
        }
    }

    function removeEntry(index) {
        state.entries.splice(index, 1);
        renderFileRows();
        updateSubmitState();
    }

    function clearSelection() {
        state.entries = [];
        fileInput.value = '';
        hideAlert();
        renderFileRows();
        updateSubmitState();
    }

    function updateSubmitState() {
        submitButton.disabled = state.entries.length === 0;
        submitButton.querySelector('.submit-label').textContent = state.entries.length === 0
            ? 'Upload All'
            : `Upload All (${state.entries.length})`;
    }

    function formatFileSize(size) {
        if (size < 1024 * 1024) {
            return `${(size / 1024).toFixed(1)} KB`;
        }
        return `${(size / (1024 * 1024)).toFixed(1)} MB`;
    }

    function escapeHtml(value) {
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function escapeAttribute(value) {
        return escapeHtml(value).replace(/`/g, '&#96;');
    }

    function startPolling() {
        if (state.pollTimer) {
            clearInterval(state.pollTimer);
        }

        state.pollTimer = setInterval(async () => {
            const ids = Array.from(state.progressMap.values())
                .filter((row) => row.contentId)
                .map((row) => row.contentId);

            if (ids.length === 0) {
                return;
            }

            try {
                const response = await fetch(`${statusUrl}?ids=${encodeURIComponent(ids.join(','))}`, {
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest',
                    },
                });
                const data = await response.json();
                if (!data.success) {
                    return;
                }

                data.statuses.forEach((statusEntry) => {
                    const row = state.progressMap.get(statusEntry.content_id);
                    if (!row) {
                        return;
                    }

                    row.status = statusEntry.status;
                    row.statusLabel = statusEntry.status.charAt(0).toUpperCase() + statusEntry.status.slice(1);
                    row.message = statusEntry.error || statusEntry.stage || statusEntry.status;
                    if (['completed', 'failed'].includes(statusEntry.status)) {
                        row.message = statusEntry.error || `${statusEntry.stage} complete`;
                    }
                });

                renderProgressList();

                const allFinished = Array.from(state.progressMap.values()).every((row) => ['completed', 'failed'].includes(row.status));
                if (allFinished) {
                    clearInterval(state.pollTimer);
                    state.pollTimer = null;
                    showAlert('Bulk upload processing finished.', 'success');
                }
            } catch (error) {
                console.error('Bulk upload polling error:', error);
            }
        }, 5000);
    }

    async function submitBulkUpload() {
        if (state.entries.length === 0) {
            showAlert('Select at least one supported file before uploading.', 'warning');
            return;
        }

        submitButton.disabled = true;
        submitButton.querySelector('.submit-label').textContent = 'Uploading...';
        showAlert('Starting chunked uploads. Keep this tab open until uploads complete.', 'info');

        // Concurrency: number of files uploading in parallel (each file's chunks are sequential)
        const concurrency = 2; // safe default for high-throughput large files
        const queue = state.entries.slice();
        const tagIds = tagsInput.value.trim();

        state.progressMap.clear();

        async function uploadWorker() {
            while (queue.length) {
                const entry = queue.shift();
                try {
                    await uploadSingleEntry(entry, tagIds);
                } catch (err) {
                    console.error('File upload failed', err);
                }
            }
        }

        // Start workers
        await Promise.all(Array.from({ length: concurrency }, () => uploadWorker()));

        // After all workers complete, start polling for processing updates
        startPolling();

        submitButton.disabled = state.entries.length === 0;
        submitButton.querySelector('.submit-label').textContent = state.entries.length === 0
            ? 'Upload All'
            : `Upload All (${state.entries.length})`;
    }

    async function uploadSingleEntry(entry, tagIds) {
        // Initialize upload session on server
        const initPayload = {
            filename: entry.file.name,
            total_size: entry.file.size,
            title_ar: entry.titleAr || '',
            title_en: entry.titleEn || '',
            tag_ids: tagIds ? tagIds.split(',').map(s => s.trim()).filter(Boolean) : []
        };

        let initData;
        try {
            initData = await uploader.initSession(initPayload);
        } catch (err) {
            state.progressMap.set(entry.file.name, {
                key: entry.file.name,
                contentId: '',
                name: entry.file.name,
                type: entry.type,
                status: 'failed',
                statusLabel: 'Failed',
                message: err.response?.error || err.message || 'Failed to initialize upload session'
            });
            renderProgressList();
            return;
        }

        const sessionId = initData.session_id;
        // Track progress by session id until we get a content_id
        state.progressMap.set(sessionId, {
            key: sessionId,
            contentId: '',
            name: entry.file.name,
            type: entry.type,
            status: 'uploading',
            statusLabel: 'Uploading',
            message: '0%'
        });
        renderProgressList();

        try {
            const lastResponse = await uploader.uploadChunks(entry.file, sessionId, (offset, total) => {
                const percent = Math.min(100, Math.round((offset / total) * 100));
                const row = state.progressMap.get(sessionId);
                if (row) {
                    row.message = `Uploading ${percent}%`;
                    row.statusLabel = `${percent}%`;
                    renderProgressList();
                }
            });

            // Finalize: server should respond with 'final' and content_id for the last chunk
            if (lastResponse && lastResponse.final && lastResponse.content_id) {
                const row = state.progressMap.get(sessionId);
                row.contentId = lastResponse.content_id;
                row.status = 'pending';
                row.statusLabel = 'Queued';
                row.message = lastResponse.message || 'Queued for processing';
                renderProgressList();
            } else {
                const row = state.progressMap.get(sessionId);
                row.status = 'pending';
                row.statusLabel = 'Queued';
                row.message = 'Queued for processing';
                renderProgressList();
            }

        } catch (err) {
            console.error('Chunk upload error', err);
            const row = state.progressMap.get(sessionId) || state.progressMap.get(entry.file.name);
            if (row) {
                row.status = 'failed';
                row.statusLabel = 'Failed';
                row.message = err.response?.error || err.message || 'Network error during chunk upload';
            }
            renderProgressList();
            return;
        }
    }

    fileInput.addEventListener('change', (event) => {
        addFiles(event.target.files);
        fileInput.value = '';
    });

    const dropzone = document.querySelector('.dropzone-area');
    dropzone.addEventListener('dragover', (event) => {
        event.preventDefault();
        dropzone.classList.add('border-primary', 'bg-primary-subtle');
    });
    dropzone.addEventListener('dragleave', () => {
        dropzone.classList.remove('border-primary', 'bg-primary-subtle');
    });
    dropzone.addEventListener('drop', (event) => {
        event.preventDefault();
        dropzone.classList.remove('border-primary', 'bg-primary-subtle');
        addFiles(event.dataTransfer.files);
    });

    submitButton.addEventListener('click', submitBulkUpload);

    updateSubmitState();
    renderFileRows();
    renderProgressList();

    if (clearButton) {
        clearButton.addEventListener('click', clearSelection);
    }

    updateDashboardSummary();
})();
