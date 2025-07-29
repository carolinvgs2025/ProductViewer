// main.js

const PRODUCTS_DATA       = window.PRODUCTS_DATA;
const ALL_ATTRIBUTE_NAMES = window.ALL_ATTRIBUTE_NAMES;
const ALL_FILTER_OPTIONS  = window.ALL_FILTER_OPTIONS;
let pendingChanges        = {};
let currentProductInModal = null;

$(document).ready(function () {
    $('.select2-filter').select2({
      placeholder: 'Select an option',
      allowClear:   true,
      closeOnSelect:false
    })
    // when you pick something…
    .on('select2:select', function(e) {
      const $sel = $(this);
      const picked = e.params.data.id;
      let   vals   = $sel.val() || [];
  
      if (picked === 'All') {
        
        // explicit “All”: reset to just All
        $sel.val(['All']).trigger('change');
      } else {
        // remove the default “All” token
        vals = vals.filter(v => v !== 'All');
        $sel.val(vals).trigger('change');
      }
    })
    // when you un‐pick something…
    .on('select2:unselect', function(e) {
      const $sel = $(this);
      const vals = $sel.val() || [];
      if (vals.length === 0) {
        // if you clear everything, go back to All
        $sel.val(['All']).trigger('change');
      }
    })
    // always run your filter logic on change
    .on('change', applyFilters);
  
    // … then the rest of your bootstrapping…
    applyFilters();
    setupViewToggle();
    setupSortButtons();
    setupSelectAllButtons();
    setupFileUpload();
    setupApplyChanges();
    setupDownloadButton();
    setupModalListeners();
    setupSortFieldButtons();
  });

// ----------------- UTILITY FUNCTIONS -----------------

function sanitizeAttr(attr) {
    return attr.replace(/ /g, '_')
               .replace(/\//g, '_')
               .replace(/[()]/g, '')
               .replace(/\+/g, 'plus')
               .replace(/:/g, '');
}

function applyFilters() {
    const filters = {};
    ALL_ATTRIBUTE_NAMES.forEach(attr => {
        const key = sanitizeAttr(attr);
        filters[key] = $(`#filter-${key}`).val() || [];
    });
    const retailFilters = $('#filter-retail').val() || [];

    document.querySelectorAll('.product').forEach(product => {
        let show = true;
        for (let key in filters) {
            const sel = filters[key];
            const val = product.getAttribute(`data-${key}`);
            if (sel.length && !sel.includes('All') && !sel.includes(val)) {
                show = false; break;
            }
        }
        if (show && retailFilters.length && !retailFilters.includes('All')) {
            show = retailFilters.some(d =>
                product.getAttribute(`data-${d}`)?.toUpperCase() === 'TRUE'
            );
        }
        product.style.display = show ? 'block' : 'none';
    });

    updateFilterOptions(); // For dynamic filter options
}


function updateFilterOptions() {
    const visible = Array.from(document.querySelectorAll('.product'))
      .filter(p => p.style.display !== 'none');
  
    // 1) ATT filters
    ALL_ATTRIBUTE_NAMES.forEach(attr => {
      const key = sanitizeAttr(attr);
      const $sel = $(`#filter-${key}`);
      const avail = new Set(visible.map(p => p.getAttribute(`data-${key}`)));
      $sel.find('option').each(function() {
        const v = $(this).val();
        if (v === 'All') return;
        $(this).prop('disabled', !avail.has(v));
      });
      $sel.trigger('change.select2');
    });
  
    // 2) Retail filter
    const $ret = $('#filter-retail');
    $ret.find('option').each(function() {
      const v = $(this).val();
      if (v === 'All') return;
      const ok = visible.some(p =>
        p.getAttribute(`data-${v}`)?.toUpperCase() === 'TRUE'
      );
      $(this).prop('disabled', !ok);
    });
    $ret.trigger('change.select2');
  }

function clearAllSortActive() {
    document.querySelectorAll('.sort-btn.active')
            .forEach(btn => btn.classList.remove('active'));
}

// ----------------- VIEW TOGGLE -----------------

function setupViewToggle() {
    document.querySelectorAll('.toggle-attr').forEach(cb => {
        cb.addEventListener('change', function () {
            const attr = this.dataset.attr;
            document.querySelectorAll(`.attr-${attr}`).forEach(el => {
                el.style.display = this.checked ? 'block' : 'none';
            });
        });
    });
}

// ----------------- SORT ATTRIBUTE BUTTONS -----------------

function setupSortButtons() {
    // Legacy single-button sort (unused now but kept for backward compatibility)
    window.sortByAttr = function (attr) {
        const grid = document.getElementById('product-grid');
        const items = Array.from(grid.children);
        items.sort((a, b) =>
            (a.getAttribute(`data-${attr}`) || '')
            .localeCompare(b.getAttribute(`data-${attr}`) || '')
        );
        items.forEach(item => grid.appendChild(item));
    };
}

// ----------------- SORT FIELD BUTTONS (▲/▼) -----------------

function sortByField(field, dir) {
    const grid = document.getElementById('product-grid');
    const items = Array.from(grid.children);

    items.sort((a, b) => {
        let aVal, bVal;
        if (field === 'description') {
            const da = a.querySelector('.grid-desc');
            const db = b.querySelector('.grid-desc');
            aVal = da ? da.textContent.trim() : '';
            bVal = db ? db.textContent.trim() : '';
        } else if (field === 'price') {
            const pa = a.querySelector('.grid-price');
            const pb = b.querySelector('.grid-price');
            const aNum = pa ? parseFloat(pa.textContent.replace(/[^0-9.]/g, '')) : 0;
            const bNum = pb ? parseFloat(pb.textContent.replace(/[^0-9.]/g, '')) : 0;
            // numeric comparison
            return dir === 'asc' ? aNum - bNum : bNum - aNum;
        } else {
            aVal = a.getAttribute(`data-${field}`) || '';
            bVal = b.getAttribute(`data-${field}`) || '';
        }

        let cmp = (field === 'price')
            ? (aVal - bVal)
            : aVal.localeCompare(bVal);

        return dir === 'asc' ? cmp : -cmp;
    });

    items.forEach(item => grid.appendChild(item));
}

function setupSortFieldButtons() {
    document.querySelectorAll('.sort-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const field = btn.dataset.attr;
            const dir   = btn.dataset.dir;
            clearAllSortActive();
            btn.classList.add('active');
            sortByField(field, dir);
        });
    });
}

// ----------------- SELECT ALL / DESELECT ALL -----------------

function setupSelectAllButtons() {
    document.getElementById('selectAllView').addEventListener('click', () => {
        document.querySelectorAll('.toggle-attr').forEach(cb => {
            cb.checked = true;
            cb.dispatchEvent(new Event('change'));
        });
    });
    document.getElementById('deselectAllView').addEventListener('click', () => {
        document.querySelectorAll('.toggle-attr').forEach(cb => {
            cb.checked = false;
            cb.dispatchEvent(new Event('change'));
        });
    });
}

// ----------------- FILE UPLOAD -----------------

function setupFileUpload() {
    document.getElementById('replace-file-button').addEventListener('click', () => {
        document.getElementById('file-upload-input').click();
    });
    document.getElementById('file-upload-input').addEventListener('change', () => {
        document.getElementById('file-upload-form').submit();
    });
}

// ----------------- APPLY CHANGES -----------------

function setupApplyChanges() {
    document.getElementById('applyChangesBtn').addEventListener('click', () => {
        const changesToSend = Object.entries(pendingChanges).flatMap(([idx, attrs]) =>
            Object.entries(attrs).map(([attr, val]) => ({
                original_index: parseInt(idx),
                attribute:      attr,
                newValue:       val
            }))
        );
        if (!changesToSend.length) return alert('No changes to apply!');
        fetch('/update_attributes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(changesToSend)
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                // prevent auto-shutdown on our own reload
                isNavigating = true;
                alert('✅ Changes have been applied successfully.');
                window.location.reload();
            } else {
                alert('Error: ' + data.message);
            }
        })
        .catch(err => alert('Request failed: ' + err));
    });
}

// ----------------- DOWNLOAD BUTTON -----------------

function setupDownloadButton() {
    document.getElementById('downloadCurrentFileBtn')
      .addEventListener('click', () => window.location.href = '/download_current_grid');
}

// ----------------- MODAL EDITING (INCLUDE DESCRIPTION & PRICE) -----------------

// Turn a <span> into an inline <input> on double-click
function makeEditable(spanEl, key) {
    if (spanEl.classList.contains('editing')) return;
    const origText = spanEl.textContent.trim();
    const input = document.createElement('input');
    input.type  = 'text';
    input.value = origText;
    spanEl.textContent = '';
    spanEl.classList.add('editing');
    spanEl.appendChild(input);
    input.focus();

    function commit() {
        const newVal = input.value.trim();
        spanEl.textContent = newVal;
        spanEl.classList.remove('editing');
        input.removeEventListener('blur', commit);
        input.removeEventListener('keydown', onKey);
        // Mark red if changed
        const originalVal = (key === 'description')
            ? currentProductInModal.description
            : currentProductInModal.price;
        updateModalStyle(spanEl, newVal, originalVal);
    }
    function onKey(e) {
        if (e.key === 'Enter') {
            commit();
            input.blur();
        }
    }
    input.addEventListener('blur', commit);
    input.addEventListener('keydown', onKey);
}

// Apply or remove red highlight on modal elements
function updateModalStyle(element, val, originalVal) {
    if (val !== originalVal) element.classList.add('changed-attribute');
    else element.classList.remove('changed-attribute');
}

function setupModalListeners() {
    const modal               = document.getElementById('productModal');
    const closeBtn            = modal.querySelector('.close-button');
    const saveBtn             = document.getElementById('saveModalChanges');
    const modalImage          = document.getElementById('modalImage');
    const modalDescription    = document.getElementById('modalDescription');
    const modalPrice          = document.getElementById('modalPrice');          // assume you added this span
    const modalAttributesDiv  = document.getElementById('modalAttributes');

    document.querySelectorAll('.product').forEach(prodEl => {
        prodEl.addEventListener('click', function () {
            const idx     = parseInt(this.dataset.productIndex);
            const product = PRODUCTS_DATA.find(p => p.original_index === idx);
            if (!product) return;
            currentProductInModal = product;

            // Image
            modalImage.src = product.image_filename
                ? `/user_images/${product.image_filename}`
                : `/static/images/notFound.png`;

            // Description
            modalDescription.textContent = product.description;
            modalDescription.classList.remove('changed-attribute');
            modalDescription.addEventListener('dblclick', () =>
                makeEditable(modalDescription, 'description')
            );

            // Price (if present in your HTML)
            if (modalPrice) {
                modalPrice.textContent = product.price;
                modalPrice.classList.remove('changed-attribute');
                modalPrice.addEventListener('dblclick', () =>
                    makeEditable(modalPrice, 'price')
                );
            }

            // Attributes
            modalAttributesDiv.innerHTML = '';
            ALL_ATTRIBUTE_NAMES.forEach(attr => {
                const safeAttr    = sanitizeAttr(attr);
                const currentVal  = product.attributes[attr];
                const originalVal = product.original_attributes[attr];

                const row = document.createElement('div');
                row.className = 'modal-attribute-row';

                const label = document.createElement('label');
                label.textContent = attr.replace('ATT ', '') + ':';
                row.appendChild(label);

                const select = document.createElement('select');
                select.className = 'modal-attribute-select';
                select.dataset.attrName = attr;

                const optsSet = new Set(ALL_FILTER_OPTIONS[attr] || []);
                optsSet.add(currentVal);
                [...optsSet].sort().forEach(val => {
                    const o = document.createElement('option');
                    o.value = val; o.textContent = val;
                    if (val === currentVal) o.selected = true;
                    select.appendChild(o);
                });

                const newOpt = document.createElement('option');
                newOpt.value = '__NEW_VALUE__';
                newOpt.textContent = 'Write a new value...';
                select.appendChild(newOpt);

                const input = document.createElement('input');
                input.type = 'text';
                input.className = 'new-value-input';
                input.style.display = 'none';

                if (!optsSet.has(currentVal)) {
                    select.value = '__NEW_VALUE__';
                    input.style.display = 'block';
                    input.value = currentVal;
                }

                select.addEventListener('change', () => {
                    if (select.value === '__NEW_VALUE__') {
                        input.style.display = 'block';
                        input.focus();
                        updateModalStyle(select, input.value.trim(), originalVal);
                    } else {
                        input.style.display = 'none';
                        updateModalStyle(select, select.value, originalVal);
                    }
                });
                input.addEventListener('input', () =>
                    updateModalStyle(select, input.value.trim(), originalVal)
                );

                row.appendChild(select);
                row.appendChild(input);
                modalAttributesDiv.appendChild(row);

                // initial color
                const initVal = select.value === '__NEW_VALUE__'
                                ? input.value.trim()
                                : select.value;
                updateModalStyle(select, initVal, originalVal);
            });

            modal.style.display = 'block';
        });
    });

    // Close modal
    closeBtn.addEventListener('click', () => modal.style.display = 'none');
    window.addEventListener('click', e => { if (e.target === modal) modal.style.display = 'none'; });

    // Save Changes
    saveBtn.addEventListener('click', () => {
        if (!currentProductInModal) return;
        const idx = currentProductInModal.original_index;
        pendingChanges[idx] = pendingChanges[idx] || {};

        // ——— PRICE VALIDATION ———
        const rawPrice = modalPrice.textContent.trim();
        // allow empty or digits + optional fractional part
        if (rawPrice && !/^\d+(\.\d+)?$/.test(rawPrice)) {
            alert('Please enter a valid price (numbers only, with optional decimal).');
            return; // abort save
        }

        // Description
        const newDesc = modalDescription.textContent.trim();
        if (newDesc !== currentProductInModal.description) {
            pendingChanges[idx]['description'] = newDesc;
            currentProductInModal.description = newDesc;
        }

        // Price
        if (modalPrice) {
            const newPrice = modalPrice.textContent.trim();
            if (newPrice !== currentProductInModal.price) {
                pendingChanges[idx]['price'] = newPrice.replace(/^\$/, '');
                currentProductInModal.price = newPrice;
            }
        }

        // Attributes
        document.querySelectorAll('.modal-attribute-select').forEach(sel => {
            const attr   = sel.dataset.attrName;
            const input  = sel.parentElement.querySelector('.new-value-input');
            const rawNew = (sel.value === '__NEW_VALUE__')
                           ? input.value.trim()
                           : sel.value;
            const orig   = currentProductInModal.original_attributes[attr];

            if (rawNew !== currentProductInModal.attributes[attr]) {
                currentProductInModal.attributes[attr] = rawNew;
                pendingChanges[idx][attr] = rawNew;
            }
        });

        updateMainGridView(idx);
        modal.style.display = 'none';
    });
}


// ----------------- UPDATE GRID VIEW -----------------
function updateMainGridView(productOriginalIndex) {
    const el  = document.querySelector(`.product[data-product-index="${productOriginalIndex}"]`);
    if (!el) return;
    const data = PRODUCTS_DATA.find(p => p.original_index === productOriginalIndex);
  
    // --- DESCRIPTION ---
    const descEl = el.querySelector('.grid-desc');
    if (descEl) {
      descEl.textContent = data.description;
      if (data.description !== data.original_description) {
        descEl.classList.add('changed-attribute');
      } else {
        descEl.classList.remove('changed-attribute');
      }
    }
  
    // --- PRICE ---
    const priceEl = el.querySelector('.grid-price');
    if (priceEl) {
       priceEl.textContent = '$' + data.price;
      if (data.price !== data.original_price) {
        priceEl.classList.add('changed-attribute');
      } else {
        priceEl.classList.remove('changed-attribute');
      }
    }
  
    // --- OTHER ATTRIBUTES (unchanged) ---
    el.querySelectorAll('.attribute-value').forEach(span => {
      const attrName    = span.dataset.attrName;
      const newVal      = data.attributes[attrName];
      const originalVal = data.original_attributes[attrName];
      span.textContent  = newVal;
      span.dataset.currentValue = newVal;
      const safeKey = sanitizeAttr(attrName);
      el.setAttribute(`data-${safeKey}`, newVal);
      if (newVal !== originalVal) span.classList.add('changed-attribute');
      else span.classList.remove('changed-attribute');
    });

      
  
    applyFilters();
  }


  // every second, ping the server
const heartbeat = setInterval(() => {
    navigator.sendBeacon('/heartbeat');
  }, 3000);
  
  // stop pinging as soon as we're unloading
  window.addEventListener('beforeunload', () => {
    clearInterval(heartbeat);
  });