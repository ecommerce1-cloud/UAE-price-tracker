document.addEventListener("DOMContentLoaded", () => {
    let priceData = null;

    // Elements
    const tableBody = document.getElementById("table-body");
    const lastUpdatedText = document.getElementById("last-updated-text");
    const searchInput = document.getElementById("search-input");
    const exportBtn = document.getElementById("export-btn");
    const logToggle = document.getElementById("log-toggle");
    const logContainer = document.getElementById("log-container");
    const logBody = document.getElementById("log-body");
    
    // Guide Modal Elements
    const guideTriggerBtn = document.getElementById("guide-trigger-btn");
    const guideModal = document.getElementById("guide-modal");
    const closeGuideBtn = document.getElementById("close-guide-btn");
    const tabBtns = document.querySelectorAll(".tab-btn");
    const tabContents = document.querySelectorAll(".tab-content");

    // 1. Fetch prices.json
    async function loadPrices() {
        try {
            // Fetch relative to current directory (works on local server and GitHub Pages)
            const response = await fetch("prices.json");
            
            if (!response.ok) {
                throw new Error("Prices file not found");
            }
            
            priceData = await response.json();
            renderDashboard(priceData);
        } catch (error) {
            console.error("Error loading price data:", error);
            renderEmptyState();
        }
    }

    // 2. Render Dashboard (Data loaded successfully)
    function renderDashboard(data) {
        // Set last updated
        if (data.last_updated) {
            lastUpdatedText.textContent = `Last Scraped: ${data.last_updated}`;
        } else {
            lastUpdatedText.textContent = "Last Scraped: Unknown";
        }

        // Set logs
        if (data.log && data.log.length > 0) {
            logBody.textContent = data.log.join("\n");
        } else {
            logBody.textContent = "No log messages generated during last run.";
        }

        // Render Table
        renderTableRows(data.products);
    }

    // 3. Render Table Rows
    function renderTableRows(products, filterText = "") {
        tableBody.innerHTML = "";
        
        const filtered = products.filter(item => {
            const nameMatch = item.name.toLowerCase().includes(filterText.toLowerCase());
            const barcodeMatch = item.barcode.includes(filterText);
            return nameMatch || barcodeMatch;
        });

        if (filtered.length === 0) {
            tableBody.innerHTML = `
                <tr>
                    <td colspan="7">
                        <div class="empty-state">
                            <span style="font-size: 2rem;">📭</span>
                            <p>No products found matching "${filterText}".</p>
                        </div>
                    </td>
                </tr>
            `;
            return;
        }

        filtered.forEach(item => {
            const tr = document.createElement("tr");
            
            // Product info
            tr.innerHTML = `
                <td class="col-product">${item.name}</td>
                <td class="col-barcode">${item.barcode}</td>
            `;

            // Platforms to render
            const platforms = ["amazon", "noon", "noon_minutes", "careem", "talabat"];
            
            platforms.forEach(platform => {
                const td = document.createElement("td");
                td.className = "col-retailer";
                
                const platData = item.prices[platform];
                
                if (!platData) {
                    td.innerHTML = `<span class="badge badge-not-found">Not Configured</span>`;
                } else if (platData.rsp) {
                    // Item found, render price with link
                    const listPriceHTML = platData.list_price 
                        ? `<span class="list-price">AED ${platData.list_price}</span>` 
                        : '';
                    
                    td.innerHTML = `
                        <a href="${platData.url}" target="_blank" class="price-cell" title="Click to view product page">
                            <span class="rsp-price">AED ${platData.rsp}</span>
                            ${listPriceHTML}
                        </a>
                    `;
                } else {
                    // Item not found or error states
                    const status = platData.status ? platData.status.toLowerCase() : '';
                    if (status.includes("not stocked") || status.includes("stocked")) {
                        td.innerHTML = `<span class="badge badge-not-stocked">Not Stocked</span>`;
                    } else if (status.includes("not found")) {
                        td.innerHTML = `<span class="badge badge-not-found">Not Found</span>`;
                    } else if (status.includes("token missing") || status.includes("missing")) {
                        td.innerHTML = `<span class="badge badge-not-found" title="Configure session token in secrets">Token Missing</span>`;
                    } else {
                        td.innerHTML = `<span class="badge badge-badge-error" title="${platData.status || 'Scraping error'}">Error</span>`;
                    }
                }
                
                tr.appendChild(td);
            });

            tableBody.appendChild(tr);
        });
    }

    // 4. Render Empty State (No file exists yet)
    function renderEmptyState() {
        lastUpdatedText.textContent = "Last Scraped: Never";
        logBody.textContent = "Log empty. Run workflow in GitHub Actions to initiate first scrape.";
        
        tableBody.innerHTML = `
            <tr>
                <td colspan="7">
                    <div class="empty-state">
                        <span style="font-size: 2.5rem;">⚙️</span>
                        <h3>No Scraped Price Data Found</h3>
                        <p>This is expected before you run your first scraper. Click "Setup Instructions" to configure your repository and run the daily scraper.</p>
                        <button id="guide-empty-btn" class="btn btn-primary" style="margin-top: 10px;">Get Started Guide</button>
                    </div>
                </td>
            </tr>
        `;
        
        // Add listener to the dynamically created guide button
        document.getElementById("guide-empty-btn")?.addEventListener("click", () => {
            guideModal.classList.remove("hidden");
        });
    }

    // 5. Search Filter Event
    searchInput.addEventListener("input", (e) => {
        if (priceData && priceData.products) {
            renderTableRows(priceData.products, e.target.value);
        }
    });

    // 6. CSV Export
    exportBtn.addEventListener("click", () => {
        if (!priceData || !priceData.products || priceData.products.length === 0) {
            alert("No data available to export.");
            return;
        }

        // Header Columns
        let csvContent = "data:text/csv;charset=utf-8,";
        csvContent += "Product Description,Barcode,Amazon RSP,Amazon List,Noon RSP,Noon List,Noon Minutes RSP,Noon Minutes List,Careem RSP,Careem List,Talabat RSP,Talabat List\n";

        // Rows
        priceData.products.forEach(item => {
            const p = item.prices;
            const row = [
                `"${item.name.replace(/"/g, '""')}"`,
                `"${item.barcode}"`,
                p.amazon?.rsp || "",
                p.amazon?.list_price || "",
                p.noon?.rsp || "",
                p.noon?.list_price || "",
                p.noon_minutes?.rsp || "",
                p.noon_minutes?.list_price || "",
                p.careem?.rsp || "",
                p.careem?.list_price || "",
                p.talabat?.rsp || "",
                p.talabat?.list_price || ""
            ];
            csvContent += row.join(",") + "\n";
        });

        // Download trigger
        const encodedUri = encodeURI(csvContent);
        const link = document.createElement("a");
        link.setAttribute("href", encodedUri);
        
        const dateStr = datetimeToFilename();
        link.setAttribute("download", `dubai_price_report_${dateStr}.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    });

    function datetimeToFilename() {
        const d = new Date();
        return `${d.getFullYear()}-${(d.getMonth()+1).toString().padStart(2, '0')}-${d.getDate().toString().padStart(2, '0')}`;
    }

    // 7. Log Terminal Accordion Toggling
    logToggle.addEventListener("click", () => {
        logToggle.classList.toggle("active");
        logContainer.classList.toggle("collapsed");
    });

    // 8. Setup Instructions Modal Handlers
    guideTriggerBtn.addEventListener("click", () => {
        guideModal.classList.remove("hidden");
    });

    closeGuideBtn.addEventListener("click", () => {
        guideModal.classList.add("hidden");
    });

    // Click outside modal content to close
    window.addEventListener("click", (e) => {
        if (e.target === guideModal) {
            guideModal.classList.add("hidden");
        }
    });

    // Tabs inside Modal
    tabBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            // Remove active classes
            tabBtns.forEach(b => b.classList.remove("active"));
            tabContents.forEach(c => c.classList.remove("active"));

            // Add active class to clicked button
            btn.classList.add("active");
            
            // Show corresponding content
            const tabId = btn.getAttribute("data-tab");
            document.getElementById(tabId).classList.add("active");
        });
    });

    // Run Initial Load
    loadPrices();
});
