// Sky Viewer Application - Aladin Lite v3
// Main application logic

class SkyViewer {
    constructor() {
        this.aladin = null;
        this.catalogs = [];
        this.starsInFov = [];
        this.allStarsInFov = []; // Store all stars before filtering

        // Selection (index-based to avoid float equality issues)
        this.selectedStar = null;
        this.selectedIndex = -1;
        this.selectionOverlay = null; // Changed name for clarity

        this.targetCoord = null;
        this.fovRadius = 25 / 60; // 25 arcmin in degrees
        this.instPA = 0;
        this.paTolerance = 30; // Default tolerance in degrees
        this.paRestrict = true; // Whether to restrict P.A. (default: enabled)

        this.magFilter = { band: '', min: null, max: null };
        this.availableColumns = [];
        this.displayColumns = ['separation', 'pa'];

        // Display mode: 'cards' or 'table'
        this.displayMode = 'cards';
        this.sortColumn = null;
        this.sortDirection = 'asc';

        // MIMIZUKU dual-field / PNG
        this.mimizukuAladin = null;
        this.mimizukuPNGMode = false;
        this.mimizukuParams = null;
        
        // Solution 1 constants
        this.HIGH_RESOLUTION_SCALE = 5;  // html2canvas scale for high resolution
        this.FIXED_OUTPUT_WIDTH = 300;   // Fixed output width per field (pixels)
        this.FIXED_OUTPUT_HEIGHT = 600;  // Fixed output height per field (pixels)

        // Fallback click handler ref
        this.__aladinHitTestHandler__ = null;

        this.init();
    }

    init() {
        this.initAladin();
        this.setupEventListeners();
        this.showStatus('Ready. Enter target and click Search.', 'info');
    }

    initAladin() {
        this.aladin = A.aladin('#aladin-lite-div', {
            survey: 'P/2MASS/color',
            fov: 1.0,
            projection: 'TAN',
            target: '18 09 01.48 -20 05 08.0',
            showReticle: true,
            showZoomControl: true,
            showFullscreenControl: true,
            showLayersControl: true,
            showGotoControl: true,
            showShareControl: false,
            showCooGrid: true
        });

        this.fovCircle = A.graphicOverlay({ color: '#ff0000', lineWidth: 2 });
        this.aladin.addOverlay(this.fovCircle);

        this.wedgesOverlay = A.graphicOverlay({ color: '#ffff00', lineWidth: 1 });
        this.aladin.addOverlay(this.wedgesOverlay);

        this.starCatalog = A.catalog({ name: 'Stars', sourceSize: 18, shape: 'square' });
        this.aladin.addCatalog(this.starCatalog);

        this.bindCatalogClickHandlers();
        this.ensureMainCanvasReady().then(() => this.attachCanvasHitTestForMainAladin());
    }

    bindCatalogClickHandlers() {
        const handler = (source) => {
            const idx = source?.data?.index ?? source?.data?.starData?.index ?? null;
            if (typeof idx === 'number') this.selectStar(idx);
        };
        try { this.starCatalog?.on?.('click', handler); this.starCatalog?.on?.('objectClicked', handler); } catch {}
        try { this.aladin?.on?.('objectClicked', handler); } catch {}
    }

    ensureMainCanvasReady(timeoutMs = 3000) {
        return new Promise(resolve => {
            const start = performance.now();
            const loop = () => {
                const canvas = document.querySelector('#aladin-lite-div canvas');
                if (canvas || performance.now() - start > timeoutMs) return resolve();
                requestAnimationFrame(loop);
            };
            loop();
        });
    }

    ensureStarCatalogAttached() {
        try { if (this.aladin && this.starCatalog) this.aladin.addCatalog(this.starCatalog); }
        catch (e) { console.warn('ensureStarCatalogAttached failed:', e); }
    }

    attachCanvasHitTestForMainAladin() {
        const container = document.querySelector('#aladin-lite-div');
        const innerCanvas = container?.querySelector('canvas');
        if (!container || !innerCanvas) return;

        const onClick = (ev) => {
            const rect = innerCanvas.getBoundingClientRect();
            const x = ev.clientX - rect.left;
            const y = ev.clientY - rect.top;
            if (!this.starsInFov?.length) return;

            let bestIdx = -1, bestDist = Infinity;
            for (let i = 0; i < this.starsInFov.length; i++) {
                const s = this.starsInFov[i];
                const [sx, sy] = this.aladin.world2pix(s.ra, s.dec) || [NaN, NaN];
                if (!isFinite(sx) || !isFinite(sy)) continue;
                const d = Math.hypot(sx - x, sy - y);
                if (d < bestDist) { bestDist = d; bestIdx = i; }
            }
            if (bestIdx >= 0 && bestDist <= 12) {
                this.selectStar(bestIdx);
            }
        };

        container.removeEventListener('click', this.__aladinHitTestHandler__);
        this.__aladinHitTestHandler__ = onClick;
        container.addEventListener('click', onClick);
    }

    setupEventListeners() {
        const bind = (id, fn, evt = 'click') => { const el = document.getElementById(id); if (el) el.addEventListener(evt, fn); };
        bind('search-button', () => this.searchTarget());
        bind('target-input', e => { if (e.key === 'Enter') this.searchTarget(); }, 'keypress');
        bind('update-pa-button', () => this.updatePA());
        bind('inst-pa-input', e => { if (e.key === 'Enter') this.updatePA(); }, 'keypress');
        bind('load-catalog-button', () => this.loadCatalogs());
        bind('change-survey-button', () => this.changeSurvey());
        bind('apply-mag-filter-button', () => this.applyMagnitudeFilter());
        bind('confirm-button', () => this.confirmObservation());
        bind('show-mimizuku-button', () => this.showMimizukuDualField());
        bind('close-mimizuku-button', () => this.closeMimizukuDualField());
        bind('toggle-png-view-button', () => this.togglePNGView());
        bind('check-observability-button', () => this.checkObservability());
        bind('view-results-button', () => this.navigateToViewer());

        const today = new Date().toISOString().split('T')[0];
        const dateEl = document.getElementById('obs-date');
        if (dateEl) dateEl.value = today;

        this.setupAccordions();
    }

    setupAccordions() {
        [{ h: 'obs-coord-header', c: 'obs-coord-content' }, { h: 'obs-check-header', c: 'obs-check-content' }]
            .forEach(({ h, c }) => {
                const header = document.getElementById(h);
                const content = document.getElementById(c);
                const icon = header?.querySelector('.accordion-icon');
                if (!header || !content) return;
                header.addEventListener('click', () => {
                    content.classList.toggle('expanded');
                    icon?.classList.toggle('expanded');
                });
            });
    }

    showLoading(show) {
        const indicator = document.getElementById('loading-indicator');
        if (indicator) indicator.style.display = show ? 'block' : 'none';
    }

    showStatus(message, type = 'info') {
        const starList = document.getElementById('star-list');
        if (starList) starList.innerHTML = `<div class="status-message ${type}">${message}</div>`;
    }

    async searchTarget() {
        const targetInput = document.getElementById('target-input')?.value?.trim();
        if (!targetInput) { this.showStatus('Please enter target coordinates.', 'error'); return; }
        this.showLoading(true);
        try {
            await this.centerOnTarget(targetInput);
            this.drawFovCircle();
            this.drawRecommendedWedges();
            this.findStarsInFov();
        } catch (e) {
            console.error('searchTarget error:', e);
            this.showStatus(`Error: ${e.message}`, 'error');
        } finally {
            this.showLoading(false);
        }
    }

    async centerOnTarget(targetString) {
        try {
            this.targetCoord = this.parseCoordinates(targetString);
            this.aladin.gotoRaDec(this.targetCoord.ra, this.targetCoord.dec);
        } catch {
            await this.aladin.gotoObject(targetString);
            await new Promise(r => setTimeout(r, 500));
            const [ra, dec] = this.aladin.getRaDec();
            this.targetCoord = { ra, dec };
        }
    }

    parseCoordinates(coordString) {
        const cleaned = coordString.replace(/[hmsd]/gi, ' ').replace(/\s+/g, ' ').trim();
        const p = cleaned.split(' ');
        if (p.length >= 6) {
            const ra = (parseFloat(p[0]) + parseFloat(p[1]) / 60 + parseFloat(p[2]) / 3600) * 15;
            const sign = p[3].startsWith('-') ? -1 : 1;
            const dec = sign * (Math.abs(parseFloat(p[3])) + parseFloat(p[4]) / 60 + parseFloat(p[5]) / 3600);
            return { ra, dec };
        }
        throw new Error('Could not parse coordinates. Use "18h09m01.48s -20d05m08.0s"');
    }

    drawFovCircle() {
        if (!this.targetCoord) return;
        this.fovCircle.removeAll();
        const circle = A.circle(this.targetCoord.ra, this.targetCoord.dec, this.fovRadius, { color: '#ff0000', lineWidth: 2 });
        this.fovCircle.add(circle);
    }

    drawRecommendedWedges() {
        if (!this.targetCoord) return;
        this.wedgesOverlay.removeAll();
        if (!this.paRestrict) return;

        const tolerance = this.paTolerance;
        const slitPA = (this.instPA + 90) % 360;

        for (let offset of [0, 180]) this.drawWedgeIndicator((slitPA + offset) % 360, tolerance);
    }

    drawWedgeIndicator(paCenter, tolerance) {
        const centerRa = this.targetCoord.ra, centerDec = this.targetCoord.dec, radius = this.fovRadius;
        const paRad = (90 - paCenter) * Math.PI / 180;
        const raOffset = radius * Math.cos(paRad) / Math.cos(centerDec * Math.PI / 180);
        const decOffset = radius * Math.sin(paRad);
        const line1 = A.polyline([[centerRa, centerDec], [centerRa - raOffset, centerDec + decOffset]], { color: 'rgba(255,255,0,0.7)', lineWidth: 5 });
        this.wedgesOverlay.add(line1);

        const pa1Rad = (90 - (paCenter - tolerance)) * Math.PI / 180;
        const pa2Rad = (90 - (paCenter + tolerance)) * Math.PI / 180;
        const ra1 = centerRa - radius * Math.cos(pa1Rad) / Math.cos(centerDec * Math.PI / 180);
        const dec1 = centerDec + radius * Math.sin(pa1Rad);
        const ra2 = centerRa - radius * Math.cos(pa2Rad) / Math.cos(centerDec * Math.PI / 180);
        const dec2 = centerDec + radius * Math.sin(pa2Rad);
        const line2 = A.polyline([[centerRa, centerDec], [ra1, dec1]], { color: 'rgba(255,255,0,0.5)', lineWidth: 3 });
        const line3 = A.polyline([[centerRa, centerDec], [ra2, dec2]], { color: 'rgba(255,255,0,0.5)', lineWidth: 3 });
        this.wedgesOverlay.add(line2);
        this.wedgesOverlay.add(line3);
    }

    updatePA() {
        this.instPA = parseFloat(document.getElementById('inst-pa-input')?.value) || 0;
        this.paTolerance = parseFloat(document.getElementById('pa-tolerance-input')?.value) || 30;
        this.paRestrict = !!document.getElementById('pa-restrict-checkbox')?.checked;

        this.drawRecommendedWedges();
        if (this.starsInFov.length) this.plotStarsOnAladin();
    }

    changeSurvey() {
        const survey = document.getElementById('survey-select')?.value;
        if (!survey) return;
        this.showLoading(true);
        try { this.aladin.setImageSurvey(survey); }
        catch (e) { console.error('changeSurvey error:', e); this.showStatus(`Error: ${e.message}`, 'error'); }
        finally { this.showLoading(false); }
    }

    applyMagnitudeFilter() {
        this.magFilter.band = document.getElementById('mag-band-select')?.value || '';
        this.magFilter.min = parseFloat(document.getElementById('mag-min')?.value) || null;
        this.magFilter.max = parseFloat(document.getElementById('mag-max')?.value) || null;
        if (this.allStarsInFov.length) this.findStarsInFov();
    }

    async loadCatalogs() {
        console.time('loadCatalogs');
        const files = document.getElementById('catalog-file')?.files;
        if (!files?.length) { this.showStatus('Please select a CSV file.', 'error'); return; }
        this.showLoading(true);
        this.catalogs = [];
        for (let f of files) {
            try {
                console.time(`  - parse ${f.name}`);
                const data = await this.parseCatalogFile(f);
                console.timeEnd(`  - parse ${f.name}`);
                console.log(`    ${data.length} rows loaded`);
                this.catalogs.push({ name: f.name, data });
            }
            catch (e) { console.error('loadCatalog error:', f.name, e); }
        }
        console.time('  - detectColumns');
        this.detectAvailableColumns();
        console.timeEnd('  - detectColumns');
        this.updateMagFilterDropdown();
        this.showLoading(false);
        this.showStatus(`Loaded ${this.catalogs.length} catalog(s).`, 'success');
        console.timeEnd('loadCatalogs');
        if (this.targetCoord) this.findStarsInFov();
    }

    parseCatalogFile(file) {
        return new Promise((resolve, reject) => {
            Papa.parse(file, { header: true, dynamicTyping: true, skipEmptyLines: true, complete: res => resolve(res.data), error: reject });
        });
    }

    detectAvailableColumns() {
        const set = new Set();
        for (const { data } of this.catalogs) {
            if (!data?.length) continue;
            let row = data[0];
            for (let i = 1; i < Math.min(5, data.length); i++) { if (Object.keys(data[i] || {}).length > Object.keys(row || {}).length) row = data[i]; }
            for (const col of Object.keys(row || {})) {
                if (['ra','RA','Ra','_RAJ2000','dec','Dec','DEC','_DEJ2000'].includes(col)) continue;
                let numeric = true;
                for (let i = 0; i < Math.min(10, data.length); i++) {
                    const v = data[i][col];
                    if (v != null && v !== '' && isNaN(parseFloat(v))) { numeric = false; break; }
                }
                if (numeric) set.add(col);
            }
        }
        this.availableColumns = [...set].sort();
    }

    updateMagFilterDropdown() {
        const select = document.getElementById('mag-band-select');
        if (!select) return;
        select.innerHTML = '<option value="">No Filter</option>';
        for (const col of this.availableColumns) {
            const opt = document.createElement('option');
            opt.value = opt.textContent = col;
            select.appendChild(opt);
        }
    }

    findStarsInFov() {
        console.time('findStarsInFov');
        if (!this.targetCoord) { this.showStatus('Please search for a target first.', 'error'); return; }
        if (!this.catalogs.length) { this.showStatus('No catalogs loaded.', 'info'); return; }

        console.time('  - search loop');
        this.starsInFov = [];
        for (const { name, data } of this.catalogs) {
            for (const row of data) {
                const raCol = this.findColumn(row, ['ra','RA','Ra','_RAJ2000']);
                const decCol = this.findColumn(row, ['dec','Dec','DEC','_DEJ2000']);
                if (!raCol || !decCol) continue;
                let ra = row[raCol], dec = row[decCol];
                if (ra == null || dec == null || isNaN(ra) || isNaN(dec)) continue;
                if (ra < 24) ra *= 15;

                const sep = this.calculateSeparation(this.targetCoord.ra, this.targetCoord.dec, ra, dec);
                if (sep <= this.fovRadius) {
                    const pa = this.calculatePositionAngle(this.targetCoord.ra, this.targetCoord.dec, ra, dec);
                    this.starsInFov.push({ catalog: name, ra, dec, separation: sep, pa, data: row });
                }
            }
        }
        console.timeEnd('  - search loop');
        console.log(`  - found ${this.starsInFov.length} stars`);

        console.time('  - sort and filter');
        this.starsInFov.sort((a, b) => a.separation - b.separation);
        if (this.starsInFov.length > 500) this.starsInFov = this.starsInFov.slice(0, 500);
        this.allStarsInFov = [...this.starsInFov];
        this.filterStars();
        console.timeEnd('  - sort and filter');

        console.time('  - displayStars');
        this.displayStars();
        console.timeEnd('  - displayStars');

        console.time('  - plotStarsOnAladin');
        this.plotStarsOnAladin();
        console.timeEnd('  - plotStarsOnAladin');
        
        // Enable the detailed view button if stars were found
        const viewButton = document.getElementById('view-results-button');
        if (viewButton) viewButton.disabled = this.starsInFov.length === 0;
        console.timeEnd('findStarsInFov');
    }

    filterStars() {
        this.starsInFov = [...this.allStarsInFov];
        if (this.magFilter.band) {
            this.starsInFov = this.starsInFov.filter(star => {
                const mag = star.data[this.magFilter.band];
                return mag != null && !isNaN(mag) &&
                       (this.magFilter.min == null || mag >= this.magFilter.min) &&
                       (this.magFilter.max == null || mag <= this.magFilter.max);
            });
        }
    }

    findColumn(obj, names) { for (const n of names) if (n in obj) return n; return null; }
    calculateSeparation(ra1, dec1, ra2, dec2) { const r1=ra1*Math.PI/180,d1=dec1*Math.PI/180,r2=ra2*Math.PI/180,d2=dec2*Math.PI/180; const a=Math.sin((d2-d1)/2)**2+Math.cos(d1)*Math.cos(d2)*Math.sin((r2-r1)/2)**2; return 2*Math.asin(Math.sqrt(a))*180/Math.PI; }
    calculatePositionAngle(ra1, dec1, ra2, dec2) { const r1=ra1*Math.PI/180,d1=dec1*Math.PI/180,r2=ra2*Math.PI/180,d2=dec2*Math.PI/180; let pa=Math.atan2(Math.sin(r2-r1),Math.cos(d1)*Math.tan(d2)-Math.sin(d1)*Math.cos(r2-r1))*180/Math.PI; return pa<0?pa+360:pa; }
    isStarRecommended(pa) { if(!this.paRestrict)return false; const slitPA=(this.instPA+90)%360; for(const o of[0,180]){const diff=Math.abs(pa-(slitPA+o)%360); if(Math.min(diff,360-diff)<this.paTolerance)return true;} return false; }
    formatRA(ra) { const h=ra/15; const hh=Math.floor(h),mm=Math.floor((h-hh)*60),ss=((h-hh)*60-mm)*60; return `${String(hh).padStart(2,'0')}:${String(mm).padStart(2,'0')}:${ss.toFixed(2).padStart(5,'0')}`; }
    formatDec(dec) { const sign=dec<0?'-':'+',a=Math.abs(dec); const dd=Math.floor(a),mm=Math.floor((a-dd)*60),ss=((a-dd)*60-mm)*60; return `${sign}${String(dd).padStart(2,'0')}:${String(mm).padStart(2,'0')}:${ss.toFixed(1).padStart(4,'0')}`; }

    displayStars() {
        const container = document.getElementById('star-list'); if (!container) return;
        if (!this.starsInFov.length) { this.showStatus('No stars found.', 'info'); return; }
        container.innerHTML = this.starsInFov.map((star, i) => {
            const isRec=this.isStarRecommended(star.pa), isSel=i===this.selectedIndex;
            const extra = this.availableColumns.map(col=>{ const v=star.data[col]; return v!=null&&v!==''?`<div class="star-catalog">${col}: ${typeof v==='number'?v.toFixed(2):v}</div>`:'' }).join('');
            return `<div class="star-item ${isRec?'recommended':''} ${isSel?'selected':''}" data-index="${i}">
              <div class="star-item-header"><span class="star-number">#${i+1}</span><span class="star-distance">${(star.separation*60).toFixed(2)}' | P.A. ${star.pa.toFixed(1)}°</span></div>
              <div class="star-coords">RA: ${this.formatRA(star.ra)} | Dec: ${this.formatDec(star.dec)}</div>
              <div class="star-catalog">${star.catalog}</div>${extra}</div>`;
        }).join('');
        container.querySelectorAll('.star-item').forEach((el, idx) => el.addEventListener('click', () => this.selectStar(idx)));
    }

    displayStarsAsTable() {
        const container = document.getElementById('star-list'); 
        if (!container) return;
        if (!this.starsInFov.length) { 
            this.showStatus('No stars found.', 'info'); 
            return; 
        }

        // Set display mode
        this.displayMode = 'table';

        // Build column headers dynamically
        const baseColumns = ['#', 'RA', 'Dec', 'Sep (")', 'P.A. (°)', 'Catalog'];
        const allColumns = [...baseColumns, ...this.availableColumns];

        // Create table HTML
        let tableHTML = '<table class="star-table"><thead><tr>';
        allColumns.forEach((col, colIndex) => {
            const isSorted = this.sortColumn === colIndex;
            const sortIcon = isSorted ? (this.sortDirection === 'asc' ? ' ▲' : ' ▼') : '';
            tableHTML += `<th data-column="${colIndex}" class="sortable">${col}${sortIcon}</th>`;
        });
        tableHTML += '</tr></thead><tbody>';

        // Add rows
        this.starsInFov.forEach((star, i) => {
            const isRec = this.isStarRecommended(star.pa);
            const isSel = i === this.selectedIndex;
            const rowClass = `${isRec ? 'recommended' : ''} ${isSel ? 'selected' : ''}`.trim();
            
            tableHTML += `<tr class="${rowClass}" data-index="${i}">`;
            tableHTML += `<td class="star-number">${i + 1}</td>`;
            tableHTML += `<td>${this.formatRA(star.ra)}</td>`;
            tableHTML += `<td>${this.formatDec(star.dec)}</td>`;
            tableHTML += `<td>${(star.separation * 60).toFixed(2)}</td>`;
            tableHTML += `<td>${star.pa.toFixed(1)}</td>`;
            tableHTML += `<td>${star.catalog || '-'}</td>`;
            
            // Add extra columns
            this.availableColumns.forEach(col => {
                const val = star.data[col];
                const displayVal = val != null && val !== '' 
                    ? (typeof val === 'number' ? val.toFixed(2) : val) 
                    : '-';
                tableHTML += `<td>${displayVal}</td>`;
            });
            
            tableHTML += '</tr>';
        });

        tableHTML += '</tbody></table>';
        container.innerHTML = tableHTML;

        // Attach click handlers for rows
        container.querySelectorAll('tr[data-index]').forEach((el, idx) => {
            el.addEventListener('click', () => this.selectStar(parseInt(el.dataset.index)));
        });

        // Attach click handlers for sortable column headers
        container.querySelectorAll('th.sortable').forEach((th) => {
            th.addEventListener('click', (e) => {
                e.stopPropagation(); // Prevent row selection
                const colIndex = parseInt(th.dataset.column);
                this.sortTableByColumn(colIndex);
            });
        });
    }

    sortTableByColumn(colIndex) {
        // Toggle sort direction if clicking same column
        if (this.sortColumn === colIndex) {
            this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
        } else {
            this.sortColumn = colIndex;
            this.sortDirection = 'asc';
        }

        // Define column names for sorting
        const baseColumns = ['#', 'RA', 'Dec', 'Sep (")', 'P.A. (°)', 'Catalog'];
        
        // Get the value for sorting from a star object
        const getValue = (star, colIndex) => {
            if (colIndex === 0) return star.index; // #
            if (colIndex === 1) return star.ra; // RA
            if (colIndex === 2) return star.dec; // Dec
            if (colIndex === 3) return star.separation; // Separation
            if (colIndex === 4) return star.pa; // P.A.
            if (colIndex === 5) return star.catalog || ''; // Catalog
            
            // Extra columns (magnitude bands, etc.)
            const extraColIndex = colIndex - baseColumns.length;
            if (extraColIndex >= 0 && extraColIndex < this.availableColumns.length) {
                const colName = this.availableColumns[extraColIndex];
                const val = star.data[colName];
                return val != null ? val : '';
            }
            return '';
        };

        // Store original indices before sorting
        this.starsInFov.forEach((star, i) => {
            star.index = i;
        });

        // Sort the stars array
        this.starsInFov.sort((a, b) => {
            let valA = getValue(a, colIndex);
            let valB = getValue(b, colIndex);

            // Handle numeric vs string comparison
            if (typeof valA === 'number' && typeof valB === 'number') {
                return this.sortDirection === 'asc' ? valA - valB : valB - valA;
            } else {
                valA = String(valA);
                valB = String(valB);
                if (this.sortDirection === 'asc') {
                    return valA.localeCompare(valB);
                } else {
                    return valB.localeCompare(valA);
                }
            }
        });

        // Update selected index if a star is selected
        if (this.selectedStar) {
            const newIndex = this.starsInFov.findIndex(star => 
                star.ra === this.selectedStar.ra && star.dec === this.selectedStar.dec
            );
            this.selectedIndex = newIndex;
        }

        // Redisplay the table
        this.displayStarsAsTable();
        this.plotStarsOnAladin();
    }

    plotStarsOnAladin() {
        this.ensureStarCatalogAttached();
        this.starCatalog.removeAll();

        const sources = this.starsInFov.map((star, index) => {
            const isRecommended = this.isStarRecommended(star.pa);
            const isSelected = (index === this.selectedIndex);

            let color = '#00BFFF'; // Default color: DeepSkyBlue
            let size = 12;
            let shape = 'square';

            if (isRecommended) {
                color = '#ff00ff'; // Recommended: magenta
            }

            if (isSelected) {
                color = '#ff0000'; // Selected: red
                size = 16;
            }

            const source = A.source(star.ra, star.dec, {
                name: `#${index + 1}`,
                data: { ...star, index, starData: star },
                shape: shape,
                color: color,
                size: size
            });

            try { source.onClick = () => this.selectStar(index); } catch {}
            return source;
        });

        this.starCatalog.addSources(sources);
        
        // Force Aladin to redraw the view to reflect changes
        try {
            this.aladin.view.requestRedraw();
        } catch (e) {
            // Fallback: trigger a minimal view change to force redraw
            try {
                const currentFov = this.aladin.getFov();
                this.aladin.setFoV(currentFov[0]);
            } catch (e2) {
                console.warn('Could not force Aladin redraw:', e2);
            }
        }
        
        this.attachCanvasHitTestForMainAladin();
    }

    selectStar(index) {
        if (index < 0 || index >= this.starsInFov.length) {
            this.selectedIndex = -1;
            this.selectedStar = null;
        } else {
            this.selectedIndex = index;
            this.selectedStar = this.starsInFov[index];
        }

        // Use the appropriate display method based on current mode
        if (this.displayMode === 'table') {
            this.displayStarsAsTable();
        } else {
            this.displayStars();
        }
        this.plotStarsOnAladin();

        ['confirm-button', 'show-mimizuku-button', 'check-observability-button', 'check-observability-button-viewer'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.disabled = (this.selectedIndex < 0);
        });
        document.querySelector('#star-list .star-item.selected')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    confirmObservation() {
        if (!this.selectedStar || !this.targetCoord) return;
        const tRA = this.formatRA(this.targetCoord.ra), tDec = this.formatDec(this.targetCoord.dec);
        const gRA = this.formatRA(this.selectedStar.ra), gDec = this.formatDec(this.selectedStar.dec);
        document.getElementById('target-coord-display').textContent = `${tRA}  ${tDec}`;
        document.getElementById('guide-star-coord-display').textContent = `${gRA}  ${gDec}`;
        document.getElementById('show-mimizuku-button').disabled = false;
    }

    // ---------- MIMIZUKU / PNG Functions ----------

    getAladinCanvasGeomForPNG() {
        const outer = document.getElementById('mimizuku-field');
        const inner = outer?.querySelector('canvas');
        if (!inner) {
            throw new Error('MIMIZUKU modal inner canvas not found');
        }
        const outerRect = outer.getBoundingClientRect();
        const innerRect = inner.getBoundingClientRect();
        return {
            innerCanvas: inner,
            cssOffsetX: innerRect.left - outerRect.left,
            cssOffsetY: innerRect.top - outerRect.top,
            cssWidth: innerRect.width,
            cssHeight: innerRect.height
        };
    }

    // app.js の extractOneFieldAsCanvas 関数をこちらに置き換えてください
    extractOneFieldAsCanvas(sourceCanvas, aladin, obj, fieldWidthDeg, fieldHeightDeg, geom, scale, angle, target, guide) {
        const [xPix, yPix] = aladin.world2pix(obj.ra, obj.dec);
        const centerX = (geom.cssOffsetX + xPix) * scale;
        const centerY = (geom.cssOffsetY + yPix) * scale;

        const eps = 0.001;
        const cosDec = Math.cos(obj.dec * Math.PI / 180);
        const dx = eps * Math.cos(angle) / cosDec;
        const dy = eps * Math.sin(angle);
        const [x1, y1] = aladin.world2pix(obj.ra - dx, obj.dec - dy);
        const [x2, y2] = aladin.world2pix(obj.ra + dx, obj.dec + dy);

        // ★★★ ここからが修正箇所 ★★★
        // 基本の回転角度を計算
        let rotation = -Math.atan2(y2 - y1, x2 - x1);

        // TargetのRAがGuideのRAより大きい場合のみ、180度追加で回転させる
        if (target.ra > guide.ra) {
            rotation += Math.PI;
        }
        // ★★★ 修正ここまで ★★★

        const [wx1, wy1] = aladin.world2pix(obj.ra - (fieldWidthDeg / 2) / cosDec, obj.dec);
        const [wx2, wy2] = aladin.world2pix(obj.ra + (fieldWidthDeg / 2) / cosDec, obj.dec);
        const widthPxCSS = Math.hypot(wx2 - wx1, wy2 - wy1);

        const [hx1, hy1] = aladin.world2pix(obj.ra, obj.dec - fieldHeightDeg / 2);
        const [hx2, hy2] = aladin.world2pix(obj.ra, obj.dec + fieldHeightDeg / 2);
        const heightPxCSS = Math.hypot(hx2 - hx1, hy2 - hy1);

        const fieldWidthPx = Math.round(widthPxCSS * scale);
        const fieldHeightPx = Math.round(heightPxCSS * scale);

        const size = Math.ceil(Math.sqrt(fieldWidthPx**2 + fieldHeightPx**2) * 2);
        const tmp = document.createElement('canvas');
        tmp.width = size;
        tmp.height = size;
        tmp.getContext('2d').drawImage(sourceCanvas, centerX - size / 2, centerY - size / 2, size, size, 0, 0, size, size);

        const rotCanvas = document.createElement('canvas');
        rotCanvas.width = size;
        rotCanvas.height = size;
        const rctx = rotCanvas.getContext('2d');
        rctx.fillStyle = '#000';
        rctx.fillRect(0, 0, size, size);
        rctx.translate(size / 2, size / 2);
        rctx.rotate(rotation);
        rctx.translate(-size / 2, -size / 2);
        rctx.drawImage(tmp, 0, 0);

        const crop = document.createElement('canvas');
        crop.width = fieldWidthPx;
        crop.height = fieldHeightPx;
        crop.getContext('2d').drawImage(rotCanvas, (size - fieldWidthPx) / 2, (size - fieldHeightPx) / 2, fieldWidthPx, fieldHeightPx, 0, 0, fieldWidthPx, fieldHeightPx);
        return crop;
    }

    /*
    extractOneFieldAsCanvas(sourceCanvas, aladin, obj, fieldWidthDeg, fieldHeightDeg, geom, scale, angle) {
        const [xPix, yPix] = aladin.world2pix(obj.ra, obj.dec);
        const centerX = (geom.cssOffsetX + xPix) * scale;
        const centerY = (geom.cssOffsetY + yPix) * scale;

        const eps = 0.001;
        const cosDec = Math.cos(obj.dec * Math.PI / 180);
        const dx = eps * Math.cos(angle) / cosDec;
        const dy = eps * Math.sin(angle);
        const [x1, y1] = aladin.world2pix(obj.ra - dx, obj.dec - dy);
        const [x2, y2] = aladin.world2pix(obj.ra + dx, obj.dec + dy);
        const rotation = -Math.atan2(y2 - y1, x2 - x1) + Math.PI;

        const [wx1, wy1] = aladin.world2pix(obj.ra - (fieldWidthDeg / 2) / cosDec, obj.dec);
        const [wx2, wy2] = aladin.world2pix(obj.ra + (fieldWidthDeg / 2) / cosDec, obj.dec);
        const widthPxCSS = Math.hypot(wx2 - wx1, wy2 - wy1);

        const [hx1, hy1] = aladin.world2pix(obj.ra, obj.dec - fieldHeightDeg / 2);
        const [hx2, hy2] = aladin.world2pix(obj.ra, obj.dec + fieldHeightDeg / 2);
        const heightPxCSS = Math.hypot(hx2 - hx1, hy2 - hy1);

        const fieldWidthPx = Math.round(widthPxCSS * scale);
        const fieldHeightPx = Math.round(heightPxCSS * scale);

        // ★★★ 修正点 ★★★ 安全マージンを 1.5 から 2 に増やす
        const size = Math.ceil(Math.sqrt(fieldWidthPx**2 + fieldHeightPx**2) * 2);
        const tmp = document.createElement('canvas');
        tmp.width = size;
        tmp.height = size;
        tmp.getContext('2d').drawImage(sourceCanvas, centerX - size / 2, centerY - size / 2, size, size, 0, 0, size, size);

        const rotCanvas = document.createElement('canvas');
        rotCanvas.width = size;
        rotCanvas.height = size;
        const rctx = rotCanvas.getContext('2d');
        rctx.fillStyle = '#000';
        rctx.fillRect(0, 0, size, size);
        rctx.translate(size / 2, size / 2);
        rctx.rotate(rotation);
        rctx.translate(-size / 2, -size / 2);
        rctx.drawImage(tmp, 0, 0);

        const crop = document.createElement('canvas');
        crop.width = fieldWidthPx;
        crop.height = fieldHeightPx;
        crop.getContext('2d').drawImage(rotCanvas, (size - fieldWidthPx) / 2, (size - fieldHeightPx) / 2, fieldWidthPx, fieldHeightPx, 0, 0, fieldWidthPx, fieldHeightPx);
        return crop;
    }
    */

    async togglePNGView() {
        if (!this.selectedStar || !this.targetCoord) return;
        this.mimizukuPNGMode = !this.mimizukuPNGMode;
        const button = document.getElementById('png-mode-text');
        if (button) button.textContent = this.mimizukuPNGMode ? 'Switch to Interactive' : 'Switch to PNG';

        if (this.mimizukuPNGMode) {
            await this.convertToPNGView();
        } else {
            const container = document.getElementById('mimizuku-view-container');
            if (container) container.innerHTML = '<div id="mimizuku-field" style="flex:1;background:#000;border:2px solid #444;position:relative;"></div>';
            this.mimizukuAladin = null;
            setTimeout(() => this.initMimizukuSingleField(), 100);
        }
    }

    async convertToPNGView() {
        if (typeof html2canvas === 'undefined') {
            alert('PNG conversion library (html2canvas) is not loaded.');
            this.mimizukuPNGMode = false;
            return;
        }
        const button = document.getElementById('png-mode-text');
        if (button) button.textContent = 'Converting...';

        try {
            await new Promise(r => setTimeout(r, 2000)); // Wait for images to render
            const div = document.getElementById('mimizuku-field');
            // 案1: scale値を3から5に増加して高解像度化
            const canvas = await html2canvas(div, { useCORS: true, allowTaint: true, backgroundColor: '#000', scale: this.HIGH_RESOLUTION_SCALE });
            const png = await this.extractAndConcatenateFields(canvas);

            this.mimizukuAladin = null; // Release Aladin instance

            const container = document.getElementById('mimizuku-view-container');
            if (container) {
                container.innerHTML = `
                <div style="display:flex;flex-direction:column;align-items:center;gap:10px;width:100%;height:100%;padding:10px;box-sizing:border-box;">
                  <div style="color:#fff;font-size:18px;font-weight:bold;">MIMIZUKU Dual Field (2'×2') - 案1: 固定サイズ表示</div>
                  <div style="flex:1;display:flex;justify-content:center;align-items:center;overflow:auto;width:100%;">
                    <img src="${png}" style="max-width:100%;max-height:100%;border:2px solid #00ff00;object-fit:contain;">
                  </div>
                  <div style="color:#aaa;font-size:14px;">Left: ${this.selectedStar.ra > this.targetCoord.ra ? 'Guide' : 'Target'} | Right: ${this.selectedStar.ra > this.targetCoord.ra ? 'Target' : 'Guide'} (1'×2' each, 固定サイズ出力)</div>
                </div>`;
            }
            if (button) button.textContent = 'Switch to Interactive View';
        } catch (e) {
            console.error('PNG conversion failed:', e);
            alert('PNG conversion failed: ' + e.message);
            this.mimizukuPNGMode = false;
            if (button) button.textContent = 'Switch to PNG View';
        }
    }

    // 案1: 固定サイズにスケールするヘルパー関数
    scaleCanvas(sourceCanvas, targetWidth, targetHeight) {
        const scaled = document.createElement('canvas');
        scaled.width = targetWidth;
        scaled.height = targetHeight;
        const ctx = scaled.getContext('2d');
        // imageSmoothingを有効にして、スケーリング時の品質を向上
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = 'high';
        ctx.drawImage(sourceCanvas, 0, 0, targetWidth, targetHeight);
        return scaled;
    }

    // app.js の extractAndConcatenateFields 関数をこちらに置き換えてください
    async extractAndConcatenateFields(sourceCanvas) {
        if (!this.mimizukuAladin) throw new Error('MIMIZUKU Aladin instance is not available');

        const { target, guide, angleRad, fovWidthArcmin, fovHeightArcmin } = this.mimizukuParams;
        const wDeg = fovWidthArcmin / 60;
        const hDeg = fovHeightArcmin / 60;
        const geom = this.getAladinCanvasGeomForPNG();
        const scale = sourceCanvas.width / geom.cssWidth;

        const isGuideRight = guide.ra > target.ra;
        const leftObj = isGuideRight ? target : guide;
        const rightObj = isGuideRight ? guide : target;

        const leftCanvas = this.extractOneFieldAsCanvas(sourceCanvas, this.mimizukuAladin, leftObj, wDeg, hDeg, geom, scale, angleRad, target, guide);
        const rightCanvas = this.extractOneFieldAsCanvas(sourceCanvas, this.mimizukuAladin, rightObj, wDeg, hDeg, geom, scale, angleRad, target, guide);

        // 案1: 固定の出力サイズにスケールアップ
        const scaledLeft = this.scaleCanvas(leftCanvas, this.FIXED_OUTPUT_WIDTH, this.FIXED_OUTPUT_HEIGHT);
        const scaledRight = this.scaleCanvas(rightCanvas, this.FIXED_OUTPUT_WIDTH, this.FIXED_OUTPUT_HEIGHT);

        // 1. スケール後の画像を結合する
        const combo = document.createElement('canvas');
        combo.width = scaledLeft.width + scaledRight.width;
        combo.height = Math.max(scaledLeft.height, scaledRight.height);
        const g = combo.getContext('2d');
        g.fillStyle = '#000';
        g.fillRect(0, 0, combo.width, combo.height);
        g.drawImage(scaledLeft, 0, 0);
        g.drawImage(scaledRight, scaledLeft.width, 0);
        g.strokeStyle = '#00ff00';
        g.lineWidth = 3;
        g.beginPath();
        g.moveTo(scaledLeft.width, 0);
        g.lineTo(scaledLeft.width, combo.height);
        g.stroke();

        // 2. 結合した画像を180度回転させる
        const rotatedCanvas = document.createElement('canvas');
        rotatedCanvas.width = combo.width;
        rotatedCanvas.height = combo.height;
        const rotCtx = rotatedCanvas.getContext('2d');

        // キャンバスの中心に原点を移動
        rotCtx.translate(rotatedCanvas.width / 2, rotatedCanvas.height / 2);
        // 180度回転
        rotCtx.rotate(Math.PI);
        // 原点を元に戻す
        rotCtx.translate(-rotatedCanvas.width / 2, -rotatedCanvas.height / 2);

        // 回転した状態で、結合した画像を描画
        rotCtx.drawImage(combo, 0, 0);

        // 3. 180度回転した最終的な画像を返す
        return rotatedCanvas.toDataURL('image/png');
    }

    /*
    async extractAndConcatenateFields(sourceCanvas) {
        if (!this.mimizukuAladin) throw new Error('MIMIZUKU Aladin instance is not available');

        const { target, guide, angleRad, fovWidthArcmin, fovHeightArcmin } = this.mimizukuParams;
        const wDeg = fovWidthArcmin / 60;
        const hDeg = fovHeightArcmin / 60;
        const geom = this.getAladinCanvasGeomForPNG();
        const scale = sourceCanvas.width / geom.cssWidth;

        const leftObj = guide.ra > target.ra ? guide : target;
        const rightObj = guide.ra > target.ra ? target : guide;

        const leftCanvas = this.extractOneFieldAsCanvas(sourceCanvas, this.mimizukuAladin, leftObj, wDeg, hDeg, geom, scale, angleRad);
        const rightCanvas = this.extractOneFieldAsCanvas(sourceCanvas, this.mimizukuAladin, rightObj, wDeg, hDeg, geom, scale, angleRad);

        const combo = document.createElement('canvas');
        combo.width = leftCanvas.width + rightCanvas.width;
        combo.height = Math.max(leftCanvas.height, rightCanvas.height);
        const g = combo.getContext('2d');
        g.fillStyle = '#000';
        g.fillRect(0, 0, combo.width, combo.height);
        g.drawImage(leftCanvas, 0, 0);
        g.drawImage(rightCanvas, leftCanvas.width, 0);
        g.strokeStyle = '#00ff00';
        g.lineWidth = 3;
        g.beginPath();
        g.moveTo(leftCanvas.width, 0);
        g.lineTo(leftCanvas.width, combo.height);
        g.stroke();
        return combo.toDataURL('image/png');
    }
    */

    showMimizukuDualField() {
        if (!this.selectedStar || !this.targetCoord) return;

        document.getElementById('mimizuku-modal').style.display = 'block';
        const t = this.targetCoord, g = this.selectedStar;
        const midRA = (t.ra + g.ra) / 2, midDec = (t.dec + g.dec) / 2;
        this.mimizukuParams = {
            target: t,
            guide: g,
            midRA,
            midDec,
            angleRad: Math.atan2(g.dec - t.dec, (g.ra - t.ra) * Math.cos(midDec * Math.PI / 180)),
            fovWidthArcmin: 1,
            fovHeightArcmin: 2
        };
        setTimeout(() => this.initMimizukuSingleField(), 100);
    }

    initMimizukuSingleField() {
        const div = document.getElementById('mimizuku-field');
        if (!div) return;
        div.innerHTML = '';

        const { target, guide, midRA, midDec } = this.mimizukuParams;
        const sep = this.calculateSeparation(target.ra, target.dec, guide.ra, guide.dec);
        
        // Calculate angular separations in RA and Dec directions
        const dRA = Math.abs(guide.ra - target.ra) * Math.cos(midDec * Math.PI / 180); // in degrees
        const dDec = Math.abs(guide.dec - target.dec); // in degrees
        
        // Aladin display has an aspect ratio of approximately 1:2.57 (height:width)
        // FoV is applied to the horizontal (width) dimension
        // So vertical FoV = horizontal FoV / 2.57
        const aspectRatio = 2.57;
        
        // Calculate required FoV based on both dimensions
        // For horizontal: need dRA * 1.5 to have margin
        // For vertical: need dDec * 1.5, but this translates to (dDec * 1.5 * aspectRatio) in horizontal FoV
        const fovForRA = dRA * 1.5;
        const fovForDec = dDec * 1.5 * aspectRatio;
        
        // Take the larger of the two to ensure both objects are visible
        const calculatedFov = Math.max(fovForRA, fovForDec);
        
        // Apply minimum of 0.15 degrees (9 arcmin) and maximum of 0.3 degrees (18 arcmin)
        const fov = Math.max(0.15, Math.min(calculatedFov, 0.3));
        
        this.mimizukuAladin = A.aladin('#mimizuku-field', {
            survey: document.getElementById('survey-select')?.value || 'P/2MASS/color',
            fov: fov,
            target: `${midRA} ${midDec}`,
            showReticle: true,
            showZoomControl: false,
            showFullscreenControl: false,
            showLayersControl: false,
            showGotoControl: false,
            showShareControl: false,
            showCooGrid: false,
            allowFullZoomout: false
        });
        setTimeout(() => this.drawMimizukuFields(this.mimizukuAladin, target, guide, this.mimizukuParams.angleRad, 1, 2), 500);
    }

    drawMimizukuFields(aladin, target, guide, angleRad, wArcmin, hArcmin) {
        const halfW = (wArcmin / 60) / 2, halfH = (hArcmin / 60) / 2;
        const ov = A.graphicOverlay({ color: '#ff0', lineWidth: 2 });
        aladin.addOverlay(ov);
        const cat = A.catalog({ name: 'Labels', sourceSize: 18 });
        aladin.addCatalog(cat);

        [target, guide].forEach((obj, i) => {
            const cosDec = Math.cos(obj.dec * Math.PI / 180);
            const corners = [
                [-halfW, -halfH], [halfW, -halfH], [halfW, halfH], [-halfW, halfH], [-halfW, -halfH]
            ].map(([dx, dy]) => {
                const rx = dx * Math.cos(angleRad) - dy * Math.sin(angleRad);
                const ry = dx * Math.sin(angleRad) + dy * Math.cos(angleRad);
                return [obj.ra + rx / cosDec, obj.dec + ry];
            });
            const color = i === 0 ? '#ff0' : '#0ff';
            const fill = i === 0 ? 'rgba(255,255,0,0.05)' : 'rgba(0,255,255,0.05)';
            ov.add(A.polygon(corners, { color, lineWidth: 3, fillColor: fill }));
            cat.addSources([A.source(obj.ra, obj.dec, { name: i === 0 ? 'Target' : 'Guide', shape: i === 0 ? 'square' : 'circle', color, size: 20 })]);
        });
    }

    closeMimizukuDualField() {
        document.getElementById('mimizuku-modal').style.display = 'none';
        this.mimizukuAladin = null;
        this.mimizukuPNGMode = false;
        const button = document.getElementById('png-mode-text');
        if (button) button.textContent = 'Switch to PNG View';
        const container = document.getElementById('mimizuku-view-container');
        if (container) container.innerHTML = '<div id="mimizuku-field" style="flex:1;background:#000;border:2px solid #444;position:relative;"></div>';
    }

    // ---------- Navigation ----------
    navigateToViewer() {
        if (!this.targetCoord || !this.starsInFov.length) return;
        
        // Store current state in sessionStorage
        // Only store the filtered stars (starsInFov) instead of full catalogs to avoid QuotaExceededError
        const viewerData = {
            targetCoord: this.targetCoord,
            targetInput: document.getElementById('target-input')?.value || '',
            instPA: this.instPA,
            paTolerance: this.paTolerance,
            paRestrict: this.paRestrict,
            starsInFov: this.starsInFov,
            allStarsInFov: this.allStarsInFov,
            availableColumns: this.availableColumns,
            magFilter: this.magFilter
        };
        
        try {
            sessionStorage.setItem('viewerData', JSON.stringify(viewerData));
            // Navigate to viewer page
            window.location.href = 'viewer.html';
        } catch (e) {
            // Handle quota exceeded error
            if (e.name === 'QuotaExceededError') {
                alert('データサイズが大きすぎます。等級フィルターを使用して星の数を減らしてください。');
            } else {
                alert('エラーが発生しました: ' + e.message);
            }
        }
    }

    // ---------- Observability (unchanged) ----------
    async checkObservability(){if(!this.targetCoord||!this.selectedStar){const r=document.getElementById('observability-results');if(r)r.innerHTML='<div style="color:#f88;padding:8px;background:#331;border-radius:4px;">Select target & guide first.</div>';return}const dateString=document.getElementById('obs-date')?.value,locationKey=document.getElementById('obs-location')?.value,resultsDiv=document.getElementById('observability-results');if(!dateString){if(resultsDiv)resultsDiv.innerHTML='<div style="color:#f88;padding:8px;background:#331;border-radius:4px;">Select a date.</div>';return}if(resultsDiv)resultsDiv.innerHTML='<div style="color:#aaa;padding:8px;">Checking...</div>';try{const loc=this.getObservatoryLocation(locationKey),obsDate=new Date(dateString+'T12:00:00'),sunTimes=this.findSunriseSunset(obsDate,loc),tInfo=this.checkTargetObservability(this.targetCoord.ra,this.targetCoord.dec,obsDate,loc),gInfo=this.checkTargetObservability(this.selectedStar.ra,this.selectedStar.dec,obsDate,loc);this.displayObservabilityResults({location:loc,sun:{sunrise:sunTimes.sunrise?.toISOString()||null,sunset:sunTimes.sunset?.toISOString()||null},twilight:{evening_astronomical:sunTimes.evening_twilight?.toISOString()||null,morning_astronomical:sunTimes.morning_twilight?.toISOString()||null},target_info:{...tInfo}},{location:loc,sun:sunTimes,twilight:sunTimes.twilight,target_info:{...gInfo}})}catch(e){console.error('Observability error:',e);if(resultsDiv)resultsDiv.innerHTML=`<div style="color:#f88;padding:8px;background:#331;border-radius:4px;">Error: ${e.message}</div>`}}
    displayObservabilityResults(targetData,guideData,resultsDivId='observability-results'){const r=document.getElementById(resultsDivId);if(!r)return;const fmt=iso=>{if(!iso)return'N/A';const p=iso.split('T');return p.length<2?'N/A':p[1].split('.')[0]||'N/A'},okT=targetData.target_info.observable,okG=guideData.target_info.observable,both=okT&&okG,color=both?'#4a4':'#a44',status=both?'✓ Observable':'✗ Not Observable';r.innerHTML=`<div style="background:#333;padding:10px;border-radius:4px;border:2px solid ${color};"><div style="font-weight:bold;color:${color};margin-bottom:8px;font-size:14px;">${status}</div><div style="font-size:11px;color:#aaa;margin-bottom:6px;"><strong>Night Times (${targetData.location.name}):</strong></div><div style="font-size:11px;margin-left:8px;margin-bottom:8px;">Sunset: ${fmt(targetData.sun.sunset)}<br>Twilight: ${fmt(targetData.twilight.evening_astronomical)} to ${fmt(targetData.twilight.morning_astronomical)}<br>Sunrise: ${fmt(targetData.sun.sunrise)}</div><div style="font-size:11px;color:#aaa;margin-bottom:6px;"><strong>Target:</strong></div><div style="font-size:11px;margin-left:8px;margin-bottom:8px;">Observable: ${okT?'✓ Yes':'✗ No'}<br>Best Time: ${fmt(targetData.target_info.best_time)}<br>Best Alt: ${targetData.target_info.best_altitude.toFixed(1)}°<br>Rise/Set: ${fmt(targetData.target_info.rise_time)} / ${fmt(targetData.target_info.set_time)}</div><div style="font-size:11px;color:#aaa;margin-bottom:6px;"><strong>Guide Star:</strong></div><div style="font-size:11px;margin-left:8px;">Observable: ${okG?'✓ Yes':'✗ No'}<br>Best Time: ${fmt(guideData.target_info.best_time)}<br>Best Alt: ${guideData.target_info.best_altitude.toFixed(1)}°<br>Rise/Set: ${fmt(guideData.target_info.rise_time)} / ${fmt(guideData.target_info.set_time)}</div></div>`}
    getObservatoryLocation(key){const m={subaru:{name:'Subaru',lat:19.826,lon:-155.4747},keck:{name:'Keck',lat:19.8283,lon:-155.4783},magellan:{name:'Magellan',lat:-29.0146,lon:-70.6926},vlt:{name:'VLT',lat:-24.6275,lon:-70.4044}};return m[key]||m.subaru}
    dateToJulianDate(d){return d.getTime()/864e5+2440587.5}
    julianDateToGMST(jd){const T=(jd-2451545)/36525;let g=280.46061837+360.98564736629*(jd-2451545)+T*T*(.000387933-T/3871e4);return(g%=360)<0?g+360:g}
    calculateLocalSiderealTime(jd,lon){let l=this.julianDateToGMST(jd)+lon;return(l%=360)<0?l+360:l}
    calculateAltitudeAzimuth(ra,dec,lst,lat){let ha=lst-ra;if(ha>180)ha-=360;if(ha<-180)ha+=360;const haR=ha*Math.PI/180,dR=dec*Math.PI/180,latR=lat*Math.PI/180;const sinA=Math.sin(dR)*Math.sin(latR)+Math.cos(dR)*Math.cos(latR)*Math.cos(haR),alt=Math.asin(sinA)*180/Math.PI;let az=Math.acos(Math.max(-1,Math.min(1,(Math.sin(dR)-Math.sin(latR)*sinA)/(Math.cos(latR)*Math.cos(Math.asin(sinA))))))*180/Math.PI;return{altitude:alt,azimuth:Math.sin(haR)>0?360-az:az}}
    calculateAirmass(alt){if(alt<-2)return 999;const h=Math.max(alt,-1);return 1/Math.sin((h+244/(165+47*h**1.1))*Math.PI/180)}
    calculateSunPosition(jd,lat,lon){const n=jd-2451545,L=(280.46+.9856474*n)%360,g=(357.528+.9856003*n)%360,lambda=L+1.915*Math.sin(g*Math.PI/180)+.02*Math.sin(2*g*Math.PI/180),eps=23.439-4e-7*n;const raR=Math.atan2(Math.cos(eps*Math.PI/180)*Math.sin(lambda*Math.PI/180),Math.cos(lambda*Math.PI/180)),decR=Math.asin(Math.sin(eps*Math.PI/180)*Math.sin(lambda*Math.PI/180));return{ra:raR*180/Math.PI,dec:decR*180/Math.PI,altitude:this.calculateAltitudeAzimuth(raR*180/Math.PI,decR*180/Math.PI,this.calculateLocalSiderealTime(jd,lon),lat).altitude}}
    findSunriseSunset(d,l){let s,r,e,m;for(let h=12;h<24;h+=.25){const t=new Date(d);t.setHours(Math.floor(h),(h%1)*60,0,0);if(this.calculateSunPosition(this.dateToJulianDate(t),l.lat,l.lon).altitude<-.5){s=t;break}}for(let h=0;h<12;h+=.25){const t=new Date(d);t.setHours(Math.floor(h),(h%1)*60,0,0);if(this.calculateSunPosition(this.dateToJulianDate(t),l.lat,l.lon).altitude>-.5){r=t;break}}for(let h=12;h<24;h+=.25){const t=new Date(d);t.setHours(Math.floor(h),(h%1)*60,0,0);if(this.calculateSunPosition(this.dateToJulianDate(t),l.lat,l.lon).altitude<-18){e=t;break}}for(let h=0;h<12;h+=.25){const t=new Date(d);t.setHours(Math.floor(h),(h%1)*60,0,0);if(this.calculateSunPosition(this.dateToJulianDate(t),l.lat,l.lon).altitude>-18){m=t;break}}return{sunrise:r,sunset:s,evening_twilight:e,morning_twilight:m}}
    checkTargetObservability(ra,dec,d,l){const sT=this.findSunriseSunset(d,l);if(!sT.evening_twilight||!sT.morning_twilight)return{observable:!1};let bestAlt=-90,bestTime=null,rise=null,set=null;for(let i=0;i<=48;i++){const t=new Date(sT.evening_twilight.getTime()+(sT.morning_twilight-sT.evening_twilight)/48*i);const alt=this.calculateAltitudeAzimuth(ra,dec,this.calculateLocalSiderealTime(this.dateToJulianDate(t),l.lon),l.lat).altitude;if(alt>30&&!rise)rise=t;if(alt<30&&rise&&!set)set=t;if(alt>bestAlt){bestAlt=alt;bestTime=t}}return{observable:bestAlt>=30,best_time:bestTime,best_altitude:bestAlt,rise_time:rise,set_time:set}}
}

document.addEventListener('DOMContentLoaded', () => {
    if (typeof A === 'undefined') {
        console.error('Aladin Lite not loaded');
        const div = document.getElementById('aladin-lite-div');
        if (div) div.innerHTML = '<div style="padding:20px;background:#7a1a1a;margin:20px;border-radius:8px;"><h3>Error: Aladin Lite library failed to load.</h3><p>Check network connection and reload.</p></div>';
        return;
    }
    if (A.init) A.init.then(() => { window.skyViewer = new SkyViewer(); }).catch(e => console.error('Aladin init failed:', e));
    else setTimeout(() => { window.skyViewer = new SkyViewer(); }, 1000);
});
