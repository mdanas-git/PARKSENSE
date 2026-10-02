/**
 * ParkSense — Smart Parking Web Application
 * Author: mdanas-git (https://github.com/mdanas-git)
 * Client-side Controller: Auth, Navigation, Telemetry, Reservations, AI Assistant, and Admin Controls.
 */

// Build revision identifier: 6d64616e61732d676974
const _CLIENT_ENGINE_SIG = "6d64616e61732d676974";

const landingScreen = document.getElementById("landingScreen");
const locationsScreen = document.getElementById("locationsScreen");
const parkingScreen = document.getElementById("parkingScreen");
const authScreen = document.getElementById("authScreen");

const authHeading = document.getElementById("authHeading");
const loginForm = document.getElementById("loginForm");
const signupForm = document.getElementById("signupForm");
const authMessage = document.getElementById("authMessage");
const authToast = document.getElementById("authToast");

// Configurable API base: when served from Flask (port 5000 or public HTTPS tunnel), use same-origin relative URLs.
// When served from standalone dev server on port 8000 or file://, fall back to http://localhost:5000.
const API_BASE = window.PARKSENSE_API_BASE || (window.location.origin && window.location.origin !== "null" && window.location.port !== "8000" ? "" : "http://localhost:5000");
let authToastTimer = null;

// Application State
let currentDashboardLocationId = 1;
let dashboardRefreshInterval = null;
let activeReservationPollTimer = null;
let reservationCountdownTimer = null;
let activeReservationData = null;
let pendingReservationTarget = null; // { slotId, slotLabel, locationId, locationName }

// ---------------------------------------------------------
// Toast Notification Utility
// ---------------------------------------------------------
function showAuthToast(message, type = "info") {
    if (!authToast) return;

    authToast.textContent = message;
    authToast.className = `auth-toast ${type} show`;

    if (authToastTimer) {
        clearTimeout(authToastTimer);
    }

    authToastTimer = setTimeout(() => {
        authToast.classList.remove("show");
    }, 3500);
}

// ---------------------------------------------------------
// Auth State Helpers
// ---------------------------------------------------------
function getAuthToken() {
    return localStorage.getItem("parksense_token");
}

function getCurrentUser() {
    try {
        return JSON.parse(localStorage.getItem("parksense_user") || "null");
    } catch {
        return null;
    }
}

function getCurrentUserRole() {
    const user = getCurrentUser();
    return (user && user.role) ? String(user.role).toLowerCase() : "user";
}

function isCurrentUserAdmin() {
    return getCurrentUserRole() === "admin";
}

function isCurrentUserEditor() {
    return getCurrentUserRole() === "editor";
}

function canUserAddLocations() {
    const role = getCurrentUserRole();
    return role === "admin" || role === "editor";
}

function canUserViewLocationLogs() {
    const role = getCurrentUserRole();
    return role === "admin" || role === "editor";
}

function setAuthState(token, user) {
    localStorage.setItem("parksense_token", token);
    localStorage.setItem("parksense_user", JSON.stringify(user));
    updateHeaderAuthState();
}

function clearAuthState() {
    localStorage.removeItem("parksense_token");
    localStorage.removeItem("parksense_user");
    if (dashboardRefreshInterval) clearInterval(dashboardRefreshInterval);
    if (reservationCountdownTimer) clearInterval(reservationCountdownTimer);
    if (activeReservationPollTimer) clearInterval(activeReservationPollTimer);
    activeReservationData = null;
    updateHeaderAuthState();
    updateAssistantVisibility(false);
}

function updateHeaderAuthState() {
    const hasToken = !!getAuthToken();
    const menuToggle = document.getElementById("menuToggle");
    if (menuToggle) {
        menuToggle.hidden = !hasToken;
    }

    const drawerUserGreeting = document.getElementById("drawerUserGreeting");
    if (drawerUserGreeting) {
        const user = getCurrentUser();
        if (user) {
            const roleBadge = user.role ? ` (${user.role.toUpperCase()})` : "";
            drawerUserGreeting.textContent = `${user.name}${roleBadge} • ${user.email}`;
        } else {
            drawerUserGreeting.textContent = "Signed in";
        }
    }

    const drawerTabAdminBtn = document.getElementById("drawerTabAdminBtn");
    if (drawerTabAdminBtn) {
        drawerTabAdminBtn.hidden = !isCurrentUserAdmin();
    }

    const drawerTabLocationLogsBtn = document.getElementById("drawerTabLocationLogsBtn");
    if (drawerTabLocationLogsBtn) {
        drawerTabLocationLogsBtn.hidden = !canUserViewLocationLogs();
    }

    const navAddLocationBtn = document.getElementById("navAddLocationBtn");
    if (navAddLocationBtn) {
        navAddLocationBtn.textContent = canUserAddLocations() ? "Add New Location" : "Request Location";
    }

    setupAddLocationRoleNotice();
}

function setAuthFeedback(message, type = "info") {
    if (!authMessage) return;
    authMessage.textContent = message || "";
    authMessage.className = message ? `auth-feedback ${type}`.trim() : "auth-feedback";
    authMessage.style.color = "";
}

function resetAuthForms() {
    loginForm.reset();
    signupForm.reset();
    setAuthFeedback("", "info");

    if (authToast) {
        authToast.classList.remove("show");
        authToast.textContent = "";
    }
}

function showLoginForm() {
    resetAuthForms();
    loginForm.hidden = false;
    signupForm.hidden = true;
    authHeading.textContent = "Welcome Back";
    const sub = document.querySelector(".auth-subtitle");
    if (sub) sub.textContent = "Log in or create your ParkSense account.";
    const loginBtn = document.getElementById("showLoginBtn");
    const signupBtn = document.getElementById("showSignupBtn");
    if (loginBtn) loginBtn.classList.remove("secondary-btn");
    if (signupBtn) signupBtn.classList.add("secondary-btn");
}

function showSignupForm() {
    resetAuthForms();
    loginForm.hidden = true;
    signupForm.hidden = false;
    authHeading.textContent = "Create Account";
    const sub = document.querySelector(".auth-subtitle");
    if (sub) sub.textContent = "Sign up to view live slots and reserve parking.";
    const loginBtn = document.getElementById("showLoginBtn");
    const signupBtn = document.getElementById("showSignupBtn");
    if (loginBtn) loginBtn.classList.add("secondary-btn");
    if (signupBtn) signupBtn.classList.remove("secondary-btn");
}

// ---------------------------------------------------------
// Screen Routing & Transitions
// ---------------------------------------------------------
function showScreen(screenToShow) {
    const protectedScreens = [locationsScreen, parkingScreen];
    const hasToken = !!getAuthToken();

    if (protectedScreens.includes(screenToShow) && !hasToken) {
        screenToShow = authScreen;
        showLoginForm();
    }

    // Stop dashboard polling if leaving dashboard
    if (screenToShow !== parkingScreen && dashboardRefreshInterval) {
        clearInterval(dashboardRefreshInterval);
        dashboardRefreshInterval = null;
    }

    [landingScreen, locationsScreen, parkingScreen, authScreen].forEach((screen) => {
        if (screen) {
            screen.hidden = true;
            screen.classList.remove("screen-enter");
        }
    });

    if (screenToShow) {
        screenToShow.hidden = false;
        void screenToShow.offsetWidth;
        screenToShow.classList.add("screen-enter");
        window.scrollTo({ top: 0, behavior: "smooth" });
    }

    updateHeaderAuthState();
    updateAssistantVisibility(hasToken && (screenToShow === locationsScreen || screenToShow === parkingScreen));

    if (screenToShow === locationsScreen) {
        loadLocations();
        checkActiveReservation();
    }
}

// ---------------------------------------------------------
// Landing & Auth Navigation Handlers
// ---------------------------------------------------------
document.getElementById("startBtn").addEventListener("click", function () {
    if (getAuthToken()) {
        showScreen(locationsScreen);
    } else {
        showScreen(authScreen);
        showLoginForm();
    }
});

document.getElementById("backFromAuthBtn").addEventListener("click", function () {
    resetAuthForms();
    showScreen(landingScreen);
});

document.getElementById("showLoginBtn").addEventListener("click", showLoginForm);
document.getElementById("showSignupBtn").addEventListener("click", showSignupForm);

document.getElementById("backToLocationsBtn").addEventListener("click", function () {
    if (dashboardRefreshInterval) clearInterval(dashboardRefreshInterval);
    currentDashboardLocationId = null;
    sessionStorage.removeItem("parksense_restore_dashboard_loc");
    showScreen(locationsScreen);
});

// ---------------------------------------------------------
// Theme Toggle Logic
// ---------------------------------------------------------
const themeToggle = document.getElementById("themeToggle");
const drawerThemeToggleBtn = document.getElementById("drawerThemeToggleBtn");

function applyTheme(theme) {
    const isDark = theme === "dark";
    document.body.classList.toggle("dark-mode", isDark);

    const nextMode = isDark ? "light" : "dark";
    themeToggle.setAttribute("aria-label", `Switch to ${nextMode} mode`);
    themeToggle.setAttribute("title", `Switch to ${nextMode} mode`);
}

const savedTheme = localStorage.getItem("parksense-theme") || "light";
applyTheme(savedTheme);

function toggleAppTheme() {
    const isDark = document.body.classList.contains("dark-mode");
    const newTheme = isDark ? "light" : "dark";
    applyTheme(newTheme);
    localStorage.setItem("parksense-theme", newTheme);
}

themeToggle.addEventListener("click", toggleAppTheme);
if (drawerThemeToggleBtn) {
    drawerThemeToggleBtn.addEventListener("click", toggleAppTheme);
}

// ---------------------------------------------------------
// Auth Form Submission (Login & Signup)
// ---------------------------------------------------------
loginForm.addEventListener("submit", async function (event) {
    event.preventDefault();

    const email = document.getElementById("loginEmail").value.trim();
    const password = document.getElementById("loginPassword").value;

    setAuthFeedback("Logging in...", "info");

    try {
        const response = await fetch(`${API_BASE}/api/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(
                response.status === 401
                    ? "Wrong email or password."
                    : (data.message || "Login failed.")
            );
        }

        setAuthState(data.token, data.user);
        resetAuthForms();

        showAuthToast("Login successful!", "success");
        showScreen(locationsScreen);

    } catch (error) {
        setAuthFeedback(error.message, "error");
    }
});

signupForm.addEventListener("submit", async function (event) {
    event.preventDefault();

    const name = document.getElementById("signupName").value.trim();
    const email = document.getElementById("signupEmail").value.trim();
    const password = document.getElementById("signupPassword").value;

    setAuthFeedback("Creating account...", "info");

    try {
        const response = await fetch(`${API_BASE}/api/signup`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, email, password })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(
                response.status === 409
                    ? "This email is already registered."
                    : (data.message || "Signup failed.")
            );
        }

        setAuthState(data.token, data.user);
        resetAuthForms();

        showAuthToast("Account created successfully!", "success");
        showScreen(locationsScreen);

    } catch (error) {
        setAuthFeedback(error.message, "error");
    }
});

// ---------------------------------------------------------
// Authenticated Navigation Bar (3 Tabs)
// ---------------------------------------------------------
const navLocationsBtn = document.getElementById("navLocationsBtn");
const navSavedLocationsBtn = document.getElementById("navSavedLocationsBtn");
const navAddLocationBtn = document.getElementById("navAddLocationBtn");

const locationsTabView = document.getElementById("locationsTabView");
const savedLocationsTabView = document.getElementById("savedLocationsTabView");
const addLocationTabView = document.getElementById("addLocationTabView");

function switchAppTab(activeTab) {
    [navLocationsBtn, navSavedLocationsBtn, navAddLocationBtn].forEach(b => b.classList.remove("active"));
    [locationsTabView, savedLocationsTabView, addLocationTabView].forEach(v => v.hidden = true);

    if (activeTab === "locations") {
        navLocationsBtn.classList.add("active");
        locationsTabView.hidden = false;
        loadLocations();
    } else if (activeTab === "saved") {
        navSavedLocationsBtn.classList.add("active");
        savedLocationsTabView.hidden = false;
        loadSavedLocations();
    } else if (activeTab === "add") {
        navAddLocationBtn.classList.add("active");
        addLocationTabView.hidden = false;
        setupAddLocationRoleNotice();
    }
}

navLocationsBtn.addEventListener("click", () => switchAppTab("locations"));
navSavedLocationsBtn.addEventListener("click", () => switchAppTab("saved"));
navAddLocationBtn.addEventListener("click", () => switchAppTab("add"));

function setupAddLocationRoleNotice() {
    const noticeTitle = document.getElementById("roleNoticeTitle");
    const noticeBody = document.getElementById("roleNoticeBody");
    const submitBtn = document.getElementById("submitLocationBtn");

    if (isCurrentUserAdmin()) {
        if (noticeTitle) noticeTitle.textContent = "Admin Access";
        if (noticeBody) noticeBody.textContent = "You are authorized to configure and immediately publish monitored parking facilities to the directory.";
        if (submitBtn) submitBtn.textContent = "Create & Publish Facility";
    } else if (isCurrentUserEditor()) {
        if (noticeTitle) noticeTitle.textContent = "Editor Access";
        if (noticeBody) noticeBody.textContent = "You are authorized to configure and immediately publish monitored parking facilities to the directory.";
        if (submitBtn) submitBtn.textContent = "Create & Publish Facility";
    } else {
        if (noticeTitle) noticeTitle.textContent = "Facility Notice";
        if (noticeBody) noticeBody.textContent = "Standard members may propose parking locations for operator review. Verified operators and administrators publish facilities directly.";
        if (submitBtn) submitBtn.textContent = "Submit Facility Proposal";
    }
}

// ---------------------------------------------------------
// Locations & Saved Locations Data Fetching & Rendering
// ---------------------------------------------------------
async function loadLocations() {
    const container = document.getElementById("locationsListContainer");
    if (!container) return;

    container.innerHTML = '<p class="loading-hint">Loading parking facilities...</p>';
    const token = getAuthToken();

    try {
        const response = await fetch(`${API_BASE}/api/locations`, {
            headers: token ? { "Authorization": `Bearer ${token}` } : {}
        });

        if (!response.ok) throw new Error("Failed to load locations");
        const data = await response.json();
        renderLocationsList(data.locations, container, false);
    } catch (err) {
        container.innerHTML = `<p class="error-hint">Unable to load locations: ${err.message}</p>`;
    }
}

async function loadSavedLocations() {
    const container = document.getElementById("savedLocationsListContainer");
    if (!container) return;

    container.innerHTML = '<p class="loading-hint">Loading your saved locations...</p>';
    const token = getAuthToken();
    if (!token) return;

    try {
        const response = await fetch(`${API_BASE}/api/user/saved-locations`, {
            headers: { "Authorization": `Bearer ${token}` }
        });

        if (!response.ok) throw new Error("Failed to load saved locations");
        const data = await response.json();

        if (data.saved_locations.length === 0) {
            container.innerHTML = `
                <div class="empty-state-card">
                    <p><strong>You haven't saved any locations yet.</strong></p>
                    <p>Click the star button on any location card in the Locations tab to quickly access it here.</p>
                </div>
            `;
            return;
        }

        renderLocationsList(data.saved_locations, container, true);
    } catch (err) {
        container.innerHTML = `<p class="error-hint">Unable to load saved locations: ${err.message}</p>`;
    }
}

function getStarSvg(isSaved) {
    if (isSaved) {
        return `<svg class="star-icon" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" fill="currentColor" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>`;
    }
    return `<svg class="star-icon" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>`;
}

function renderLocationsList(locations, container, isSavedView) {
    if (!locations || locations.length === 0) {
        container.innerHTML = '<p class="empty-state">No locations available.</p>';
        return;
    }

    const isAdmin = isCurrentUserAdmin();
    container.innerHTML = "";
    locations.forEach(loc => {
        const card = document.createElement("article");
        card.className = "location-card-interactive";
        card.setAttribute("role", "button");
        card.setAttribute("tabindex", "0");
        card.setAttribute("aria-label", `View dashboard for ${loc.name}`);

        const isOnline = loc.status === "ONLINE";
        const statusClass = isOnline ? "online" : "offline";
        const statusLabel = isOnline ? "Online" : "Offline / Pending";
        const isSaved = !!loc.is_saved;

        card.innerHTML = `
            <div class="loc-card-body">
                <div class="loc-card-top">
                    <h3>${escapeHtml(loc.name)}</h3>
                    <span class="status-pill ${statusClass}">${statusLabel}</span>
                </div>
                <p>${escapeHtml(loc.address)}</p>
                <div class="loc-card-meta">
                    <span><strong>${loc.total_slots}</strong> Total Slots</span>
                    <span>•</span>
                    <span>${escapeHtml(loc.status_summary)}</span>
                </div>
            </div>
            <div class="loc-card-actions">
                ${isAdmin ? `
                <button
                    class="loc-action-btn loc-delete-btn"
                    type="button"
                    data-id="${loc.id}"
                    data-name="${escapeHtml(loc.name)}"
                    aria-label="Delete location ${escapeHtml(loc.name)}"
                    title="Delete location (Admin only)"
                >
                    <svg class="trash-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                        <polyline points="3 6 5 6 21 6"></polyline>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                        <line x1="10" y1="11" x2="10" y2="17"></line>
                        <line x1="14" y1="11" x2="14" y2="17"></line>
                    </svg>
                </button>` : ''}
                <button
                    class="star-btn ${isSaved ? 'is-saved' : ''}"
                    type="button"
                    data-id="${loc.id}"
                    data-saved="${isSaved}"
                    aria-label="${isSaved ? 'Remove from saved' : 'Save location'}"
                    title="${isSaved ? 'Remove from saved' : 'Save location'}"
                >
                    ${getStarSvg(isSaved)}
                </button>
            </div>
        `;

        // Card click navigates to dashboard
        card.addEventListener("click", () => {
            openParkingDashboard(loc.id);
        });

        // Star button click toggles saved without opening dashboard
        const starBtn = card.querySelector(".star-btn");
        if (starBtn) {
            starBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                toggleSaveLocation(loc.id, starBtn, isSavedView);
            });
        }

        // Delete button click triggers deletion dialog
        const deleteBtn = card.querySelector(".loc-delete-btn");
        if (deleteBtn) {
            deleteBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                promptDeleteLocation(loc.id, loc.name);
            });
        }

        container.appendChild(card);
    });
}

async function toggleSaveLocation(locationId, starBtn, isSavedView) {
    const token = getAuthToken();
    if (!token) return;

    const currentlySaved = starBtn.dataset.saved === "true";
    const method = currentlySaved ? "DELETE" : "POST";

    // Immediate optimistic UI response with clean SVG
    const nextSaved = !currentlySaved;
    starBtn.dataset.saved = String(nextSaved);
    starBtn.innerHTML = getStarSvg(nextSaved);
    starBtn.classList.toggle("is-saved", nextSaved);

    try {
        const response = await fetch(`${API_BASE}/api/user/saved-locations/${locationId}`, {
            method,
            headers: { "Authorization": `Bearer ${token}` }
        });

        if (!response.ok) throw new Error("Failed to update saved location");

        showAuthToast(nextSaved ? "Location saved to favourites!" : "Location removed from favourites", "info");

        // If in saved view, refresh list to reflect deletion
        if (isSavedView && !nextSaved) {
            loadSavedLocations();
        }
    } catch (err) {
        // Rollback on error
        starBtn.dataset.saved = String(currentlySaved);
        starBtn.innerHTML = getStarSvg(currentlySaved);
        starBtn.classList.toggle("is-saved", currentlySaved);
        showAuthToast(err.message, "error");
    }
}

// ---------------------------------------------------------
// Add New Location Form Handler
// ---------------------------------------------------------
const addLocationForm = document.getElementById("addLocationForm");
const addLocationMessage = document.getElementById("addLocationMessage");

addLocationForm.addEventListener("submit", async function (event) {
    event.preventDefault();

    const name = document.getElementById("newLocName").value.trim();
    const address = document.getElementById("newLocAddress").value.trim();
    const total_slots = parseInt(document.getElementById("newLocSlots").value, 10);

    const token = getAuthToken();
    if (!token) return;

    addLocationMessage.textContent = "Submitting...";
    addLocationMessage.style.color = "#666";

    try {
        const response = await fetch(`${API_BASE}/api/locations`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${token}`
            },
            body: JSON.stringify({ name, address, total_slots })
        });

        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.message || "Failed to add location");
        }

        addLocationMessage.textContent = data.message;
        addLocationMessage.style.color = "green";
        showAuthToast(data.message, "success");
        addLocationForm.reset();

        setTimeout(() => {
            addLocationMessage.textContent = "";
            switchAppTab("locations");
        }, 1500);

    } catch (err) {
        addLocationMessage.textContent = err.message;
        addLocationMessage.style.color = "red";
        showAuthToast(err.message, "error");
    }
});

// ---------------------------------------------------------
// Detailed Parking Dashboard
// ---------------------------------------------------------
function openParkingDashboard(locationId) {
    currentDashboardLocationId = locationId;
    const adminDeleteBtn = document.getElementById("adminDeleteLocationBtn");
    if (adminDeleteBtn) {
        adminDeleteBtn.hidden = !isCurrentUserAdmin();
    }
    showScreen(parkingScreen);
    fetchDashboardData(locationId);

    // Poll live dashboard status every 5 seconds
    if (dashboardRefreshInterval) clearInterval(dashboardRefreshInterval);
    dashboardRefreshInterval = setInterval(() => {
        fetchDashboardData(currentDashboardLocationId);
    }, 5000);
}

const refreshDashboardBtn = document.getElementById("refreshDashboardBtn");
if (refreshDashboardBtn) {
    refreshDashboardBtn.addEventListener("click", () => {
        refreshDashboardBtn.classList.add("spinning");
        if (currentDashboardLocationId) {
            sessionStorage.setItem("parksense_restore_dashboard_loc", String(currentDashboardLocationId));
        }
        window.location.reload();
    });
}

const adminDeleteLocationBtn = document.getElementById("adminDeleteLocationBtn");
if (adminDeleteLocationBtn) {
    adminDeleteLocationBtn.addEventListener("click", () => {
        if (!currentDashboardLocationId) return;
        const locName = document.getElementById("dashboardLocName")?.textContent || "this location";
        promptDeleteLocation(currentDashboardLocationId, locName, true);
    });
}

async function promptDeleteLocation(locationId, locationName, returnToLocations = false) {
    if (!isCurrentUserAdmin()) {
        showAuthToast("Administrator privileges required.", "error");
        return;
    }

    const confirmed = confirm(`Are you sure you want to permanently delete "${locationName}"?\n\nThis will remove the location, all monitored slots, and any active reservations. This action cannot be undone.`);
    if (!confirmed) return;

    const token = getAuthToken();
    if (!token) {
        showAuthToast("Please log in again.", "error");
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/api/locations/${locationId}`, {
            method: "DELETE",
            headers: {
                "Authorization": `Bearer ${token}`
            }
        });

        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.message || "Failed to delete location");
        }

        showAuthToast(data.message || `Deleted "${locationName}" successfully.`, "success");

        // Reload locations and saved locations
        loadLocations();
        loadSavedLocations();
        checkActiveReservation();
        if (canUserViewLocationLogs()) {
            fetchLocationLogs();
        }

        if (returnToLocations) {
            if (dashboardRefreshInterval) clearInterval(dashboardRefreshInterval);
            currentDashboardLocationId = null;
            showScreen(locationsScreen);
        }
    } catch (err) {
        showAuthToast(err.message, "error");
    }
}

async function fetchDashboardData(locationId) {
    const token = getAuthToken();

    try {
        const response = await fetch(`${API_BASE}/api/locations/${locationId}?_t=${Date.now()}`, {
            cache: "no-store",
            headers: token ? { "Authorization": `Bearer ${token}` } : {}
        });

        if (!response.ok) throw new Error("Failed to load dashboard data");
        const data = await response.json();
        renderDashboard(data.location);

        if (token) {
            checkActiveReservation();
        }
    } catch (err) {
        console.error("Dashboard fetch error:", err);
    }
}

function renderDashboard(loc) {
    document.getElementById("dashboardLocName").textContent = loc.name;
    document.getElementById("dashboardLocAddress").textContent = loc.address;

    const pill = document.getElementById("dashboardStatusPill");
    pill.textContent = loc.connection_pill;
    pill.className = `status-pill ${loc.device_status === "ONLINE" ? "online" : "offline"}`;

    const lastUpdate = document.getElementById("dashboardLastUpdate");
    if (loc.is_fresh && loc.last_sensor_update) {
        lastUpdate.textContent = `Last sensor update: ${loc.last_sensor_update} UTC (Live)`;
    } else {
        lastUpdate.textContent = "Sensor offline • Connection pending";
    }

    // Summary counts
    document.getElementById("dashTotalSlots").textContent = loc.summary.total_slots;
    document.getElementById("dashAvailSlots").textContent = loc.summary.available !== null ? loc.summary.available : "—";
    document.getElementById("dashOccupiedSlots").textContent = loc.summary.occupied !== null ? loc.summary.occupied : "—";
    document.getElementById("dashReservedSlots").textContent = loc.summary.reserved !== null ? loc.summary.reserved : "—";
    document.getElementById("dashUnknownSlots").textContent = loc.summary.unknown;

    const recEl = document.getElementById("dashRecommendedSlot");
    if (loc.recommended_slot && loc.recommended_slot !== "Not available") {
        recEl.innerHTML = `<span class="rec-badge available">✓ ${escapeHtml(loc.recommended_slot)}</span>`;
    } else {
        recEl.innerHTML = `<span class="rec-badge unavailable">Not available</span>`;
    }

    const slotsPill = document.getElementById("dashSlotsStatePill");
    slotsPill.textContent = loc.device_status === "ONLINE" ? "Live Monitoring" : "Status unknown";
    slotsPill.className = `status-pill ${loc.device_status === "ONLINE" ? "online" : "offline"}`;

    const notice = document.getElementById("dashNoticeText");
    if (loc.device_status === "ONLINE") {
        notice.textContent = "Live sensor data active. Available slots may be reserved for five minutes.";
    } else {
        notice.textContent = "Availability and reservations will be enabled after the parking sensors and backend are connected.";
    }

    renderDashboardSlots(loc.slots, loc.id, loc.name);
}

function renderDashboardSlots(slots, locationId, locationName) {
    const grid = document.getElementById("dashboardSlotGrid");
    grid.innerHTML = "";

    slots.forEach(slot => {
        const article = document.createElement("article");
        article.className = "dashboard-slot";

        let statusClass = "status-unknown";
        if (slot.status === "AVAILABLE") statusClass = "status-available";
        else if (slot.status === "OCCUPIED") statusClass = "status-occupied";
        else if (slot.status === "RESERVED") statusClass = "status-reserved";

        let actionHtml = `<span class="slot-status ${statusClass}">${slot.status}</span>`;
        if (slot.status === "RESERVED" && slot.reserved_by) {
            const rawName = String(slot.reserved_by).trim();
            const firstWord = rawName.split(/\s+/)[0] || rawName;
            actionHtml = `
                <div class="slot-reserved-wrap">
                    <span class="slot-status ${statusClass}">${slot.status}</span>
                    <span class="slot-reserved-by">By ${escapeHtml(firstWord)}</span>
                </div>
            `;
        } else if (slot.can_reserve) {
            actionHtml = `
                <div class="slot-action-wrap">
                    <span class="slot-status ${statusClass}">${slot.status}</span>
                    <button class="slot-reserve-btn" type="button" data-slot-id="${slot.id}" data-slot-label="${slot.label}">Reserve (5 min)</button>
                </div>
            `;
        }

        article.innerHTML = `
            <div class="slot-left">
                <div class="slot-label" aria-hidden="true">${escapeHtml(slot.label)}</div>
                <div class="slot-details">
                    <h4>Slot ${slot.slot_number}</h4>
                </div>
            </div>
            <div class="slot-right">
                ${actionHtml}
            </div>
        `;

        const reserveBtn = article.querySelector(".slot-reserve-btn");
        if (reserveBtn) {
            reserveBtn.addEventListener("click", () => {
                promptReservation(slot.id, slot.label, locationId, locationName);
            });
        }

        grid.appendChild(article);
    });
}

// ---------------------------------------------------------
// 5-Minute Reservation Workflow
// ---------------------------------------------------------
const reserveModalBackdrop = document.getElementById("reserveModalBackdrop");
const reserveModalText = document.getElementById("reserveModalText");
const confirmReserveBtn = document.getElementById("confirmReserveBtn");
const cancelReserveModalBtn = document.getElementById("cancelReserveModalBtn");
const reserveModalFeedback = document.getElementById("reserveModalFeedback");

function promptReservation(slotId, slotLabel, locationId, locationName) {
    pendingReservationTarget = { slotId, slotLabel, locationId, locationName };
    reserveModalText.textContent = `Reserve Slot ${slotLabel} at ${locationName} for 5 minutes?`;
    reserveModalFeedback.textContent = "";
    reserveModalBackdrop.hidden = false;
}

cancelReserveModalBtn.addEventListener("click", () => {
    reserveModalBackdrop.hidden = true;
    pendingReservationTarget = null;
});

confirmReserveBtn.addEventListener("click", async () => {
    if (!pendingReservationTarget) return;

    const token = getAuthToken();
    if (!token) return;

    confirmReserveBtn.disabled = true;
    reserveModalFeedback.textContent = "Processing reservation...";
    reserveModalFeedback.style.color = "#666";

    try {
        const response = await fetch(`${API_BASE}/api/reservations`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${token}`
            },
            body: JSON.stringify({
                slot_id: pendingReservationTarget.slotId,
                location_id: pendingReservationTarget.locationId
            })
        });

        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.message || "Reservation failed.");
        }

        reserveModalBackdrop.hidden = true;
        showAuthToast("Slot reserved for 5 minutes!", "success");
        pendingReservationTarget = null;

        startReservationTimer(data.reservation);
        fetchDashboardData(currentDashboardLocationId);

    } catch (err) {
        reserveModalFeedback.textContent = err.message;
        reserveModalFeedback.style.color = "red";
    } finally {
        confirmReserveBtn.disabled = false;
    }
});

// Reservation countdown and synchronization
function startReservationTimer(reservation) {
    activeReservationData = reservation;
    if (reservationCountdownTimer) clearInterval(reservationCountdownTimer);

    let remainingSeconds = reservation.remaining_seconds || 300;

    function updateDisplay() {
        if (remainingSeconds <= 0) {
            clearInterval(reservationCountdownTimer);
            hideReservationBanners();
            showAuthToast("Your reservation has expired.", "info");
            fetchDashboardData(currentDashboardLocationId);
            return;
        }

        const mins = String(Math.floor(remainingSeconds / 60)).padStart(2, "0");
        const secs = String(remainingSeconds % 60).padStart(2, "0");
        const timeStr = `${mins}:${secs}`;

        // Global banner
        const globalBanner = document.getElementById("globalResBanner");
        if (globalBanner) {
            globalBanner.hidden = false;
            document.getElementById("globalResText").textContent = `Slot ${reservation.slot_label} at ${reservation.location_name} reserved`;
            document.getElementById("globalResTimer").textContent = timeStr;
        }

        // Dashboard specific banner
        const dashCard = document.getElementById("dashActiveResCard");
        if (dashCard) {
            if (currentDashboardLocationId === reservation.location_id) {
                dashCard.hidden = false;
                document.getElementById("dashResTitle").textContent = `Slot ${reservation.slot_label} is reserved for you`;
                document.getElementById("dashResCountdown").textContent = timeStr;
            } else {
                dashCard.hidden = true;
            }
        }

        remainingSeconds--;
    }

    updateDisplay();
    reservationCountdownTimer = setInterval(updateDisplay, 1000);
}

function hideReservationBanners() {
    const globalBanner = document.getElementById("globalResBanner");
    if (globalBanner) globalBanner.hidden = true;

    const dashCard = document.getElementById("dashActiveResCard");
    if (dashCard) dashCard.hidden = true;
}

// Cancel reservation action
async function handleCancelReservation() {
    if (!activeReservationData) return;
    const confirmCancel = confirm("Are you sure you want to cancel your reservation? This slot will become available for other drivers.");
    if (!confirmCancel) return;

    const token = getAuthToken();
    try {
        const response = await fetch(`${API_BASE}/api/reservations/${activeReservationData.id}`, {
            method: "DELETE",
            headers: { "Authorization": `Bearer ${token}` }
        });

        if (!response.ok) throw new Error("Failed to cancel reservation");

        clearInterval(reservationCountdownTimer);
        activeReservationData = null;
        hideReservationBanners();
        showAuthToast("Reservation cancelled successfully.", "info");
        fetchDashboardData(currentDashboardLocationId);

    } catch (err) {
        showAuthToast(err.message, "error");
    }
}

document.getElementById("globalResCancelBtn").addEventListener("click", handleCancelReservation);
document.getElementById("dashCancelResBtn").addEventListener("click", handleCancelReservation);

document.getElementById("globalResViewBtn").addEventListener("click", () => {
    if (activeReservationData) {
        openParkingDashboard(activeReservationData.location_id);
    }
});

async function checkActiveReservation() {
    const token = getAuthToken();
    if (!token) return;

    try {
        const response = await fetch(`${API_BASE}/api/user/active-reservation`, {
            headers: { "Authorization": `Bearer ${token}` }
        });

        if (response.ok) {
            const data = await response.json();
            if (data.active_reservation) {
                startReservationTimer(data.active_reservation);
            } else {
                if (activeReservationData) {
                    if (reservationCountdownTimer) clearInterval(reservationCountdownTimer);
                    activeReservationData = null;
                }
                hideReservationBanners();
            }
        }
    } catch (err) {
        console.warn("Could not check active reservation:", err);
    }
}

// ---------------------------------------------------------
// Hamburger Menu Drawer (Settings, Profile & Data, Privacy)
// ---------------------------------------------------------
const menuToggle = document.getElementById("menuToggle");
const appMenuDrawer = document.getElementById("appMenuDrawer");
const drawerBackdrop = document.getElementById("drawerBackdrop");
const closeDrawerBtn = document.getElementById("closeDrawerBtn");

function openDrawer() {
    appMenuDrawer.hidden = false;
    drawerBackdrop.hidden = false;
    updateHeaderAuthState();
    loadUserProfile();
}

function closeDrawer() {
    appMenuDrawer.hidden = true;
    drawerBackdrop.hidden = true;
}

if (menuToggle) menuToggle.addEventListener("click", openDrawer);
if (closeDrawerBtn) closeDrawerBtn.addEventListener("click", closeDrawer);
if (drawerBackdrop) drawerBackdrop.addEventListener("click", closeDrawer);

// Drawer internal tab navigation
const drawerTabSettingsBtn = document.getElementById("drawerTabSettingsBtn");
const drawerTabProfileBtn = document.getElementById("drawerTabProfileBtn");
const drawerTabPrivacyBtn = document.getElementById("drawerTabPrivacyBtn");
const drawerTabLocationLogsBtn = document.getElementById("drawerTabLocationLogsBtn");
const drawerTabAdminBtn = document.getElementById("drawerTabAdminBtn");

const drawerSettingsView = document.getElementById("drawerSettingsView");
const drawerProfileView = document.getElementById("drawerProfileView");
const drawerPrivacyView = document.getElementById("drawerPrivacyView");
const drawerLocationLogsView = document.getElementById("drawerLocationLogsView");
const drawerAdminView = document.getElementById("drawerAdminView");

function switchDrawerTab(tab) {
    const tabs = [drawerTabSettingsBtn, drawerTabProfileBtn, drawerTabPrivacyBtn, drawerTabLocationLogsBtn, drawerTabAdminBtn].filter(Boolean);
    const views = [drawerSettingsView, drawerProfileView, drawerPrivacyView, drawerLocationLogsView, drawerAdminView].filter(Boolean);
    tabs.forEach(b => b.classList.remove("active"));
    views.forEach(v => v.hidden = true);

    if (tab === "settings") {
        drawerTabSettingsBtn.classList.add("active");
        drawerSettingsView.hidden = false;
    } else if (tab === "profile") {
        drawerTabProfileBtn.classList.add("active");
        drawerProfileView.hidden = false;
        loadUserProfile();
    } else if (tab === "privacy") {
        drawerTabPrivacyBtn.classList.add("active");
        drawerPrivacyView.hidden = false;
    } else if (tab === "location-logs") {
        if (drawerTabLocationLogsBtn) drawerTabLocationLogsBtn.classList.add("active");
        if (drawerLocationLogsView) drawerLocationLogsView.hidden = false;
        fetchLocationLogs();
    } else if (tab === "admin") {
        if (drawerTabAdminBtn) drawerTabAdminBtn.classList.add("active");
        if (drawerAdminView) drawerAdminView.hidden = false;
        loadAdminData();
    }
}

if (drawerTabSettingsBtn) drawerTabSettingsBtn.addEventListener("click", () => switchDrawerTab("settings"));
if (drawerTabProfileBtn) drawerTabProfileBtn.addEventListener("click", () => switchDrawerTab("profile"));
if (drawerTabPrivacyBtn) drawerTabPrivacyBtn.addEventListener("click", () => switchDrawerTab("privacy"));
if (drawerTabLocationLogsBtn) drawerTabLocationLogsBtn.addEventListener("click", () => switchDrawerTab("location-logs"));
if (drawerTabAdminBtn) drawerTabAdminBtn.addEventListener("click", () => switchDrawerTab("admin"));

const refreshAdminUsersBtn = document.getElementById("refreshAdminUsersBtn");
const refreshAdminLoginsBtn = document.getElementById("refreshAdminLoginsBtn");
const refreshLocationLogsBtn = document.getElementById("refreshLocationLogsBtn");

if (refreshAdminUsersBtn) refreshAdminUsersBtn.addEventListener("click", fetchAdminUsers);
if (refreshAdminLoginsBtn) refreshAdminLoginsBtn.addEventListener("click", fetchAdminLoginLogs);
if (refreshLocationLogsBtn) refreshLocationLogsBtn.addEventListener("click", fetchLocationLogs);

async function loadAdminData() {
    if (!isCurrentUserAdmin()) return;
    await Promise.all([fetchAdminUsers(), fetchAdminLoginLogs()]);
}

async function fetchAdminUsers() {
    const tbody = document.getElementById("adminUsersListBody");
    if (!tbody) return;
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; opacity:0.6;">Loading users...</td></tr>`;
    try {
        const response = await fetch(`${API_BASE}/api/admin/users`, {
            headers: { "Authorization": `Bearer ${getAuthToken()}` }
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || "Failed to load users");

        const currentUserId = getCurrentUser()?.id;
        tbody.innerHTML = "";
        data.users.forEach(u => {
            const tr = document.createElement("tr");
            const isSelf = (u.id === currentUserId);
            const statusBadge = u.is_suspended
                ? `<span class="admin-badge status-suspended">Suspended</span>`
                : `<span class="admin-badge status-active">Active</span>`;

            let roleCell = "";
            if (isSelf) {
                roleCell = `<span class="admin-badge" style="background:#e0f2fe;color:#0369a1;">Admin (You)</span>`;
            } else {
                roleCell = `
                    <select class="admin-role-select" data-user-id="${u.id}" data-user-name="${escapeHtml(u.name)}">
                        <option value="user" ${u.role === 'user' ? 'selected' : ''}>User</option>
                        <option value="editor" ${u.role === 'editor' ? 'selected' : ''}>Editor</option>
                        <option value="admin" ${u.role === 'admin' ? 'selected' : ''}>Admin</option>
                    </select>
                `;
            }

            let actionBtn = "";
            if (!isSelf && u.role !== "admin") {
                if (u.is_suspended) {
                    actionBtn = `<button class="admin-action-btn admin-reactivate-btn" data-user-id="${u.id}" data-action="unsuspend">Reactivate</button>`;
                } else {
                    actionBtn = `<button class="admin-action-btn admin-suspend-btn" data-user-id="${u.id}" data-action="suspend">Suspend</button>`;
                }
            } else if (isSelf) {
                actionBtn = `<span style="font-size:0.75rem;opacity:0.6;">(You)</span>`;
            } else {
                actionBtn = `<span style="font-size:0.75rem;opacity:0.6;">Admin</span>`;
            }

            const pwdVal = u.password || "12345678";
            tr.innerHTML = `
                <td>
                    <strong>${escapeHtml(u.name)}</strong>
                    <div style="font-size:0.75rem;opacity:0.7;">${escapeHtml(u.email)}</div>
                </td>
                <td>${roleCell}</td>
                <td>${statusBadge}</td>
                <td>
                    <div class="admin-pwd-cell">
                        <span class="admin-pwd-text" title="Click to copy password">${escapeHtml(pwdVal)}</span>
                        <button class="admin-pwd-edit-btn" data-user-id="${u.id}" data-name="${escapeHtml(u.name)}" data-current-pwd="${escapeHtml(pwdVal)}" title="Set/Edit Password">✏️</button>
                    </div>
                </td>
                <td>${actionBtn}</td>
            `;

            const pwdEl = tr.querySelector(".admin-pwd-text");
            if (pwdEl) {
                pwdEl.addEventListener("click", () => {
                    if (navigator.clipboard) {
                        navigator.clipboard.writeText(pwdVal).then(() => {
                            showAuthToast(`Copied password for ${u.name}!`, "success");
                        }).catch(() => {});
                    }
                });
            }

            const pwdEditBtn = tr.querySelector(".admin-pwd-edit-btn");
            if (pwdEditBtn) {
                pwdEditBtn.addEventListener("click", async () => {
                    const targetName = pwdEditBtn.getAttribute("data-name");
                    const currentVal = pwdEditBtn.getAttribute("data-current-pwd") || "";
                    const newPwd = prompt(`Enter new exact password for ${targetName}:`, currentVal);
                    if (newPwd !== null && newPwd.trim().length >= 4) {
                        await setAdminUserPassword(u.id, newPwd.trim());
                    } else if (newPwd !== null) {
                        showAuthToast("Password must be at least 4 characters.", "error");
                    }
                });
            }

            const roleSelect = tr.querySelector(".admin-role-select");
            if (roleSelect) {
                roleSelect.addEventListener("change", async (e) => {
                    const newRole = e.target.value;
                    const userName = roleSelect.getAttribute("data-user-name");
                    await setAdminUserRole(u.id, newRole, userName);
                });
            }

            const btn = tr.querySelector(".admin-action-btn");
            if (btn) {
                btn.addEventListener("click", async (e) => {
                    const uid = e.target.getAttribute("data-user-id");
                    const act = e.target.getAttribute("data-action");
                    await toggleUserSuspension(uid, act === "suspend");
                });
            }

            tbody.appendChild(tr);
        });
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="5" style="color:red;font-size:0.8rem;">${escapeHtml(err.message)}</td></tr>`;
    }
}

async function setAdminUserRole(userId, newRole, userName) {
    try {
        const response = await fetch(`${API_BASE}/api/admin/users/${userId}/role`, {
            method: "PUT",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${getAuthToken()}`
            },
            body: JSON.stringify({ role: newRole })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || "Failed to update role");
        showAuthToast(data.message || `Role updated to ${newRole}.`, "success");
        fetchAdminUsers();
    } catch (err) {
        showAuthToast(err.message, "error");
        fetchAdminUsers();
    }
}

async function setAdminUserPassword(userId, newPassword) {
    try {
        const response = await fetch(`${API_BASE}/api/admin/users/${userId}/password`, {
            method: "PUT",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${getAuthToken()}`
            },
            body: JSON.stringify({ password: newPassword })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || "Failed to update password");
        showAuthToast(data.message || "Password updated successfully!", "success");
        fetchAdminUsers();
    } catch (err) {
        showAuthToast(err.message, "error");
    }
}

async function fetchLocationLogs() {
    const tbody = document.getElementById("locationLogsListBody");
    if (!tbody) return;
    tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; opacity:0.6;">Loading location logs...</td></tr>`;

    const token = getAuthToken();
    if (!token) return;

    try {
        const response = await fetch(`${API_BASE}/api/locations/logs`, {
            headers: { "Authorization": `Bearer ${token}` }
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || "Failed to load location logs");

        const locations = data.locations || [];
        if (locations.length === 0) {
            tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; opacity:0.6;">No location records found.</td></tr>`;
            return;
        }

        const isAdmin = isCurrentUserAdmin();
        const isEditor = isCurrentUserEditor();
        tbody.innerHTML = "";

        locations.forEach(loc => {
            const tr = document.createElement("tr");
            const isApproved = (loc.proposal_status === "approved" || loc.is_published === 1);
            const statusBadge = isApproved
                ? `<span class="admin-badge status-active">Approved</span>`
                : `<span class="admin-badge" style="background:#fef3c7;color:#b45309;border-color:#fde68a;">Pending</span>`;

            let actionHtml = "";
            if (!isApproved && (isAdmin || isEditor)) {
                actionHtml += `<button class="admin-action-btn admin-approve-btn" data-loc-id="${loc.id}">Approve</button> `;
            }
            if (isAdmin) {
                actionHtml += `<button class="admin-action-btn admin-suspend-btn loc-log-delete-btn" data-loc-id="${loc.id}" data-loc-name="${escapeHtml(loc.name)}">Delete</button>`;
            } else if (!actionHtml) {
                actionHtml = `<span style="font-size:0.75rem;opacity:0.6;">None</span>`;
            }

            tr.innerHTML = `
                <td>
                    <strong>${escapeHtml(loc.name)}</strong>
                    <div style="font-size:0.75rem;opacity:0.7;">${escapeHtml(loc.address)}</div>
                    <div style="font-size:0.7rem;color:#64748b;margin-top:2px;">
                        By: ${escapeHtml(loc.created_by_name || "System")} (${escapeHtml(loc.created_by_email || "—")})
                    </div>
                </td>
                <td><strong>${loc.total_slots}</strong></td>
                <td>${statusBadge}</td>
                <td>${actionHtml}</td>
            `;

            const approveBtn = tr.querySelector(".admin-approve-btn");
            if (approveBtn) {
                approveBtn.addEventListener("click", async () => {
                    await approveLocationProposal(loc.id, loc.name);
                });
            }

            const delBtn = tr.querySelector(".loc-log-delete-btn");
            if (delBtn) {
                delBtn.addEventListener("click", () => {
                    promptDeleteLocation(loc.id, loc.name);
                });
            }

            tbody.appendChild(tr);
        });
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="4" style="color:red;font-size:0.8rem;">${escapeHtml(err.message)}</td></tr>`;
    }
}

async function approveLocationProposal(locationId, locationName) {
    const token = getAuthToken();
    if (!token) return;
    try {
        const response = await fetch(`${API_BASE}/api/locations/${locationId}/approve`, {
            method: "PUT",
            headers: {
                "Authorization": `Bearer ${token}`
            }
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || "Failed to approve location");
        showAuthToast(data.message || `Location "${locationName}" approved and published!`, "success");
        fetchLocationLogs();
        loadLocations();
    } catch (err) {
        showAuthToast(err.message, "error");
    }
}


async function toggleUserSuspension(userId, suspend) {
    try {
        const response = await fetch(`${API_BASE}/api/admin/users/${userId}/suspend`, {
            method: "PUT",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${getAuthToken()}`
            },
            body: JSON.stringify({ suspend })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || "Failed to update account status");
        showAuthToast(data.message, "success");
        fetchAdminUsers();
    } catch (err) {
        showAuthToast(err.message, "error");
    }
}

async function fetchAdminLoginLogs() {
    const tbody = document.getElementById("adminLoginsListBody");
    if (!tbody) return;
    tbody.innerHTML = `<tr><td colspan="3" style="text-align:center; opacity:0.6;">Loading admin logs...</td></tr>`;
    try {
        const response = await fetch(`${API_BASE}/api/admin/logins`, {
            headers: { "Authorization": `Bearer ${getAuthToken()}` }
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || "Failed to load login logs");

        tbody.innerHTML = "";
        data.logs.slice(0, 50).forEach(log => {
            const tr = document.createElement("tr");
            let badgeClass = "status-active";
            if (log.status === "FAILED") badgeClass = "status-suspended";
            else if (log.status === "SUSPENDED" || log.status === "LOCKED_OUT") badgeClass = "status-suspended";

            tr.innerHTML = `
                <td style="font-size:0.75rem;white-space:nowrap;">${escapeHtml(log.timestamp)}</td>
                <td>
                    <div style="font-weight:500;">${escapeHtml(log.email)}</div>
                </td>
                <td><span class="admin-badge ${badgeClass}">${escapeHtml(log.status)}</span></td>
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="3" style="color:red;font-size:0.8rem;">${escapeHtml(err.message)}</td></tr>`;
    }
}

// Change Password
const changePasswordForm = document.getElementById("changePasswordForm");
const changePasswordMsg = document.getElementById("changePasswordMsg");

changePasswordForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const current_password = document.getElementById("currPassword").value;
    const new_password = document.getElementById("newPassword").value;

    const token = getAuthToken();
    if (!token) return;

    changePasswordMsg.textContent = "Updating password...";
    changePasswordMsg.style.color = "#666";

    try {
        const response = await fetch(`${API_BASE}/api/auth/change-password`, {
            method: "PUT",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${token}`
            },
            body: JSON.stringify({ current_password, new_password })
        });

        const data = await response.json();
        if (!response.ok) throw new Error(data.message || "Failed to update password");

        changePasswordMsg.textContent = "Password updated successfully!";
        changePasswordMsg.style.color = "green";
        changePasswordForm.reset();
        showAuthToast("Password updated successfully!", "success");

    } catch (err) {
        changePasswordMsg.textContent = err.message;
        changePasswordMsg.style.color = "red";
    }
});

// Logout
const logoutBtn = document.getElementById("logoutBtn");
logoutBtn.addEventListener("click", () => {
    const confirmLogout = confirm("Are you sure you want to log out of ParkSense?");
    if (!confirmLogout) return;

    clearAuthState();
    closeDrawer();
    showAuthToast("You have been logged out.", "info");
    showScreen(landingScreen);
});

// Profile & Data Management
async function loadUserProfile() {
    const token = getAuthToken();
    if (!token) return;

    try {
        const response = await fetch(`${API_BASE}/api/profile`, {
            headers: { "Authorization": `Bearer ${token}` }
        });

        if (!response.ok) return;
        const data = await response.json();
        const user = data.user;

        document.getElementById("profileName").value = user.name || "";
        document.getElementById("profileEmail").value = user.email || "";
        document.getElementById("profilePhone").value = user.phone_number || "";
        document.getElementById("profileVehicleName").value = user.vehicle_name || "";
        document.getElementById("profileVehicleReg").value = user.vehicle_reg_number || "";

        // Update local storage record
        localStorage.setItem("parksense_user", JSON.stringify(user));
        updateHeaderAuthState();
    } catch (err) {
        console.warn("Could not load user profile:", err);
    }
}

const profileForm = document.getElementById("profileForm");
const profileFormMsg = document.getElementById("profileFormMsg");

profileForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const token = getAuthToken();
    if (!token) return;

    const name = document.getElementById("profileName").value.trim();
    const phone_number = document.getElementById("profilePhone").value.trim();
    const vehicle_name = document.getElementById("profileVehicleName").value.trim();
    const vehicle_reg_number = document.getElementById("profileVehicleReg").value.trim();

    profileFormMsg.textContent = "Saving profile...";
    profileFormMsg.style.color = "#666";

    try {
        const response = await fetch(`${API_BASE}/api/profile`, {
            method: "PUT",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${token}`
            },
            body: JSON.stringify({ name, phone_number, vehicle_name, vehicle_reg_number })
        });

        const data = await response.json();
        if (!response.ok) throw new Error(data.message || "Failed to update profile");

        profileFormMsg.textContent = "Profile updated successfully!";
        profileFormMsg.style.color = "green";
        setAuthState(token, data.user);
        showAuthToast("Profile saved!", "success");

    } catch (err) {
        profileFormMsg.textContent = err.message;
        profileFormMsg.style.color = "red";
    }
});

// Account Deletion Workflow
const deleteAccountTriggerBtn = document.getElementById("deleteAccountTriggerBtn");
const deleteModalBackdrop = document.getElementById("deleteModalBackdrop");
const cancelDeleteModalBtn = document.getElementById("cancelDeleteModalBtn");
const confirmDeleteAccountBtn = document.getElementById("confirmDeleteAccountBtn");
const deleteModalFeedback = document.getElementById("deleteModalFeedback");

deleteAccountTriggerBtn.addEventListener("click", () => {
    deleteModalFeedback.textContent = "";
    deleteModalBackdrop.hidden = false;
});

cancelDeleteModalBtn.addEventListener("click", () => {
    deleteModalBackdrop.hidden = true;
});

confirmDeleteAccountBtn.addEventListener("click", async () => {
    const token = getAuthToken();
    if (!token) return;

    confirmDeleteAccountBtn.disabled = true;
    deleteModalFeedback.textContent = "Deleting account and all associated records...";
    deleteModalFeedback.style.color = "#666";

    try {
        const response = await fetch(`${API_BASE}/api/profile/account`, {
            method: "DELETE",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${token}`
            },
            body: JSON.stringify({ confirm: true })
        });

        const data = await response.json();
        if (!response.ok) throw new Error(data.message || "Account deletion failed");

        deleteModalBackdrop.hidden = true;
        closeDrawer();
        clearAuthState();
        showAuthToast("Account deleted successfully.", "info");
        showScreen(landingScreen);

    } catch (err) {
        deleteModalFeedback.textContent = err.message;
        deleteModalFeedback.style.color = "red";
    } finally {
        confirmDeleteAccountBtn.disabled = false;
    }
});

// ---------------------------------------------------------
// Helper: HTML Escaping for XSS safety
// ---------------------------------------------------------
function escapeHtml(str) {
    if (!str) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// =========================================================
// ParkSense Offline AI Assistant Frontend Controller
// =========================================================

const assistantWidgetContainer = document.getElementById("assistantWidgetContainer");
const assistantFabBtn = document.getElementById("assistantFabBtn");
const assistantChatPanel = document.getElementById("assistantChatPanel");
const assistantClearBtn = document.getElementById("assistantClearBtn");
const assistantCloseBtn = document.getElementById("assistantCloseBtn");
const assistantMessages = document.getElementById("assistantMessages");
const assistantSuggestionsBar = document.getElementById("assistantSuggestionsBar");
const assistantInputForm = document.getElementById("assistantInputForm");
const assistantQueryInput = document.getElementById("assistantQueryInput");
const assistantEngineBadge = document.getElementById("assistantEngineBadge");

const defaultAssistantSuggestions = [
    "Check live UIT status",
    "Which slot is recommended?",
    "My active reservation",
    "How do reservations work?",
    "Saved locations",
    "Data & privacy",
    "What is ParkSense?",
    "Who am I?"
];

let currentActiveSuggestions = [...defaultAssistantSuggestions];

// Keyword dictionary for fuzzy similarity matching
const promptKeywordMap = {
    "Check live UIT status": ["uit", "status", "live", "free", "available", "parking", "spots", "slots", "check", "monitor", "telemetry", "state", "sensor"],
    "Which slot is recommended?": ["which", "recommend", "recommended", "best", "where", "slot", "spot", "find", "suggest", "available", "clear"],
    "My active reservation": ["my", "active", "reservation", "booked", "booking", "hold", "time", "expire", "countdown", "mine", "current", "cancel"],
    "How do reservations work?": ["reservation", "reservations", "how", "work", "rule", "rules", "policy", "5 min", "five min", "reserve", "timer", "limit"],
    "Saved locations": ["saved", "location", "locations", "favorite", "favorites", "bookmark", "facilities", "facility", "save", "find"],
    "Data & privacy": ["data", "privacy", "security", "safe", "protect", "password", "store", "private", "encryption"],
    "What is ParkSense?": ["what", "parksense", "about", "explain", "features", "overview", "system", "app"],
    "Who am I?": ["who", "am", "i", "account", "profile", "user", "name", "vehicle", "car", "license"]
};

function matchPromptScore(prompt, query) {
    const pLower = prompt.toLowerCase();
    const q = query.trim().toLowerCase();
    if (!q) return 0;

    if (pLower.includes(q)) return 100;

    const tokens = q.split(/\s+/).filter(Boolean);
    let score = 0;

    for (const t of tokens) {
        if (pLower.includes(t)) {
            score += 50;
        }
        const keywords = promptKeywordMap[prompt] || [];
        for (const kw of keywords) {
            if (kw.startsWith(t) || t.startsWith(kw) || kw.includes(t)) {
                score += 30;
            }
        }
    }
    return score;
}

function updateAssistantVisibility(show) {
    if (assistantWidgetContainer) {
        assistantWidgetContainer.hidden = !show;
    }
    if (!show && assistantChatPanel) {
        assistantChatPanel.hidden = true;
    }
}

function formatAssistantMarkdown(rawText) {
    if (!rawText) return "";
    let html = escapeHtml(rawText);

    // Bold **text**
    html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");

    // Inline code `text`
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");

    // Status badges
    html = html.replace(/\[AVAILABLE\]/g, '<span class="assistant-badge available">AVAILABLE</span>');
    html = html.replace(/\[OCCUPIED\]/g, '<span class="assistant-badge occupied">OCCUPIED</span>');
    html = html.replace(/\[RESERVED\]/g, '<span class="assistant-badge reserved">RESERVED</span>');
    html = html.replace(/\[UNKNOWN\s*(?:\/\s*OFFLINE)?\]/g, '<span class="assistant-badge unknown">UNKNOWN</span>');

    // Split paragraphs and lists
    const lines = html.split("\n");
    let inList = false;
    let listType = "";
    const processedLines = [];

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!line) {
            if (inList) {
                processedLines.push(listType === "ul" ? "</ul>" : "</ol>");
                inList = false;
            }
            continue;
        }

        if (line.startsWith("- ") || line.startsWith("* ")) {
            if (!inList || listType !== "ul") {
                if (inList) processedLines.push(listType === "ul" ? "</ul>" : "</ol>");
                processedLines.push("<ul>");
                inList = true;
                listType = "ul";
            }
            processedLines.push(`<li>${line.substring(2)}</li>`);
        } else if (/^\d+\.\s+/.test(line)) {
            if (!inList || listType !== "ol") {
                if (inList) processedLines.push(listType === "ul" ? "</ul>" : "</ol>");
                processedLines.push("<ol>");
                inList = true;
                listType = "ol";
            }
            processedLines.push(`<li>${line.replace(/^\d+\.\s+/, "")}</li>`);
        } else {
            if (inList) {
                processedLines.push(listType === "ul" ? "</ul>" : "</ol>");
                inList = false;
            }
            processedLines.push(`<p>${line}</p>`);
        }
    }
    if (inList) {
        processedLines.push(listType === "ul" ? "</ul>" : "</ol>");
    }

    return processedLines.join("");
}

function appendAssistantMessage(role, contentHtml, isTyping = false) {
    if (!assistantMessages) return null;

    const msgWrapper = document.createElement("div");
    msgWrapper.className = `assistant-msg ${role}`;

    const bubble = document.createElement("div");
    bubble.className = "assistant-bubble";
    bubble.innerHTML = contentHtml;
    msgWrapper.appendChild(bubble);

    if (!isTyping) {
        const timeSpan = document.createElement("span");
        timeSpan.className = "assistant-msg-time";
        const now = new Date();
        timeSpan.textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        msgWrapper.appendChild(timeSpan);
    }

    assistantMessages.appendChild(msgWrapper);
    assistantMessages.scrollTop = assistantMessages.scrollHeight;
    return msgWrapper;
}

let chipDragMoved = false;

function renderAssistantSuggestions(suggestionsList, isFiltered = false, matchedList = []) {
    if (!assistantSuggestionsBar) return;
    assistantSuggestionsBar.innerHTML = "";

    const items = Array.isArray(suggestionsList) && suggestionsList.length > 0
        ? suggestionsList
        : defaultAssistantSuggestions;

    const matchedSet = new Set(matchedList || []);

    items.forEach((itemText) => {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "assistant-chip";
        if (matchedSet.has(itemText)) {
            chip.classList.add("highlighted-match");
        }
        chip.textContent = itemText;
        chip.addEventListener("click", () => {
            if (chipDragMoved) return; // Prevent click when user was dragging/sliding
            if (assistantQueryInput) {
                assistantQueryInput.value = itemText;
            }
            sendAssistantQuery(itemText);
        });
        assistantSuggestionsBar.appendChild(chip);
    });
}

function updateSuggestionsOnInput() {
    if (!assistantQueryInput) return;
    const query = assistantQueryInput.value.trim().toLowerCase();

    if (!query) {
        renderAssistantSuggestions(currentActiveSuggestions, false, []);
        return;
    }

    const scored = currentActiveSuggestions.map((prompt) => ({
        prompt,
        score: matchPromptScore(prompt, query)
    }));

    const matched = scored.filter(item => item.score > 0);
    const unmatched = scored.filter(item => item.score === 0);

    if (matched.length > 0) {
        // User requirement: Sort matched prompts in alphabetical order and slide in front!
        matched.sort((a, b) => a.prompt.localeCompare(b.prompt));

        const matchedPrompts = matched.map(m => m.prompt);
        const reordered = [
            ...matchedPrompts,
            ...unmatched.map(u => u.prompt)
        ];

        renderAssistantSuggestions(reordered, true, matchedPrompts);

        // Smoothly slide container to the front
        if (assistantSuggestionsBar) {
            assistantSuggestionsBar.scrollTo({ left: 0, behavior: "smooth" });
        }
    } else {
        renderAssistantSuggestions(currentActiveSuggestions, false, []);
    }
}

function initAssistantChat() {
    if (!assistantMessages) return;
    if (assistantMessages.children.length === 0) {
        appendAssistantMessage(
            "assistant",
            `<p><strong>Hello! I am your ParkSense Assistant.</strong> I can check live slot telemetry, track your 5-minute reservations, explain sensor & gate rules, or show your vehicle details.</p>
             <p>Click any quick prompt below or type your question!</p>`
        );
        renderAssistantSuggestions(currentActiveSuggestions, false, []);
    }
}

async function sendAssistantQuery(queryText) {
    if (!queryText || !queryText.trim()) return;
    const cleanText = queryText.trim();

    appendAssistantMessage("user", escapeHtml(cleanText));
    if (assistantQueryInput) {
        assistantQueryInput.value = "";
        updateSuggestionsOnInput();
    }

    // Show typing indicator
    const typingElem = appendAssistantMessage(
        "assistant",
        '<div class="assistant-typing-dots"><span></span><span></span><span></span></div>',
        true
    );

    const token = getAuthToken();
    try {
        const resp = await fetch(`${API_BASE}/api/assistant/chat`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${token}`
            },
            body: JSON.stringify({ message: cleanText })
        });

        if (!resp.ok) {
            throw new Error(`Server returned status ${resp.status}`);
        }

        const data = await resp.json();
        if (typingElem && typingElem.parentNode) {
            typingElem.parentNode.removeChild(typingElem);
        }

        const formattedReply = formatAssistantMarkdown(data.reply);
        appendAssistantMessage("assistant", formattedReply);

        if (assistantEngineBadge) {
            assistantEngineBadge.textContent = data.engine === "local-ollama-slm" ? "Local SLM" : "ParkSense Assistant";
        }

        if (Array.isArray(data.suggestions) && data.suggestions.length > 0) {
            const combined = [...data.suggestions];
            defaultAssistantSuggestions.forEach((p) => {
                if (!combined.includes(p)) combined.push(p);
            });
            currentActiveSuggestions = combined;
            renderAssistantSuggestions(currentActiveSuggestions, false, []);
            if (assistantSuggestionsBar) {
                assistantSuggestionsBar.scrollTo({ left: 0, behavior: "smooth" });
            }
        }

    } catch (err) {
        console.error("Assistant chat error:", err);
        if (typingElem && typingElem.parentNode) {
            typingElem.parentNode.removeChild(typingElem);
        }
        appendAssistantMessage(
            "assistant",
            "<p><strong>Notice:</strong> Unable to connect to the backend service. Please verify the Python server is running on port 5000.</p>"
        );
    }
}

// Wire Assistant UI Event Listeners
if (assistantFabBtn) {
    assistantFabBtn.addEventListener("click", () => {
        if (!assistantChatPanel) return;
        const isCurrentlyHidden = assistantChatPanel.hidden;
        assistantChatPanel.hidden = !isCurrentlyHidden;

        if (isCurrentlyHidden) {
            initAssistantChat();
            if (assistantQueryInput) {
                setTimeout(() => assistantQueryInput.focus(), 100);
            }
        }
    });
}

if (assistantCloseBtn) {
    assistantCloseBtn.addEventListener("click", () => {
        if (assistantChatPanel) {
            assistantChatPanel.hidden = true;
        }
    });
}

if (assistantClearBtn) {
    assistantClearBtn.addEventListener("click", () => {
        if (assistantMessages) {
            assistantMessages.innerHTML = "";
            currentActiveSuggestions = [...defaultAssistantSuggestions];
            initAssistantChat();
        }
    });
}

if (assistantInputForm) {
    assistantInputForm.addEventListener("submit", (e) => {
        e.preventDefault();
        if (assistantQueryInput) {
            sendAssistantQuery(assistantQueryInput.value);
        }
    });
}

// Real-time keyword filtering & alphabetical sorting to front
if (assistantQueryInput) {
    assistantQueryInput.addEventListener("input", updateSuggestionsOnInput);
}

// Quick suggestions slide navigation controls
const suggestionsSlideLeft = document.getElementById("suggestionsSlideLeft");
const suggestionsSlideRight = document.getElementById("suggestionsSlideRight");

if (suggestionsSlideLeft && assistantSuggestionsBar) {
    suggestionsSlideLeft.addEventListener("click", () => {
        assistantSuggestionsBar.scrollBy({ left: -160, behavior: "smooth" });
    });
}

if (suggestionsSlideRight && assistantSuggestionsBar) {
    suggestionsSlideRight.addEventListener("click", () => {
        assistantSuggestionsBar.scrollBy({ left: 160, behavior: "smooth" });
    });
}

// Drag-to-slide & wheel-slide for assistant suggestions
if (assistantSuggestionsBar) {
    let isMouseDown = false;
    let dragStartX = 0;
    let dragScrollLeft = 0;

    assistantSuggestionsBar.addEventListener("mousedown", (e) => {
        isMouseDown = true;
        chipDragMoved = false;
        dragStartX = e.pageX - assistantSuggestionsBar.offsetLeft;
        dragScrollLeft = assistantSuggestionsBar.scrollLeft;
    });

    window.addEventListener("mouseup", () => {
        if (isMouseDown) {
            isMouseDown = false;
            assistantSuggestionsBar.classList.remove("active-dragging");
            setTimeout(() => { chipDragMoved = false; }, 60);
        }
    });

    assistantSuggestionsBar.addEventListener("mousemove", (e) => {
        if (!isMouseDown) return;
        const currentX = e.pageX - assistantSuggestionsBar.offsetLeft;
        const diff = currentX - dragStartX;
        if (Math.abs(diff) > 4) {
            chipDragMoved = true;
            assistantSuggestionsBar.classList.add("active-dragging");
        }
        assistantSuggestionsBar.scrollLeft = dragScrollLeft - (diff * 1.5);
    });

    assistantSuggestionsBar.addEventListener("wheel", (e) => {
        if (e.deltaY !== 0) {
            e.preventDefault();
            assistantSuggestionsBar.scrollLeft += e.deltaY;
        }
    }, { passive: false });
}

// ---------------------------------------------------------
// Initial App Boot
// ---------------------------------------------------------
updateHeaderAuthState();
if (getAuthToken()) {
    checkActiveReservation();
    const restoreLocId = sessionStorage.getItem("parksense_restore_dashboard_loc");
    if (restoreLocId) {
        sessionStorage.removeItem("parksense_restore_dashboard_loc");
        openParkingDashboard(parseInt(restoreLocId, 10));
    }
}