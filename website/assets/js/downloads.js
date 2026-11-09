/**
 * BitChat Download Center - Platform Detection & Dynamic Filtering
 */

(function () {
  'use strict';

  function detectOS() {
    const userAgent = window.navigator.userAgent.toLowerCase();
    const platform = (window.navigator.userAgentData && window.navigator.userAgentData.platform)
      ? window.navigator.userAgentData.platform.toLowerCase()
      : window.navigator.platform.toLowerCase();

    if (platform.includes('win') || userAgent.includes('windows')) {
      return 'windows';
    }
    if (platform.includes('mac') || userAgent.includes('macintosh') || userAgent.includes('mac os')) {
      return 'macos';
    }
    if (platform.includes('linux') || userAgent.includes('linux') || userAgent.includes('x11')) {
      return 'linux';
    }
    return 'unknown';
  }

  function initDownloadExperience() {
    const os = detectOS();
    const osBadge = document.getElementById('detected-os-badge');
    const osTitle = document.getElementById('detected-os-title');
    const osHeroCard = document.getElementById('detected-hero-card');

    // Update detected banner if elements exist
    if (osBadge && osTitle) {
      if (os === 'windows') {
        osBadge.innerHTML = `
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <path d="M0 3.449L9.75 2.1v9.451H0m10.949-9.602L24 0v11.4H10.949M0 12.6h9.75v9.451L0 20.699M10.949 12.6H24V24l-12.901-1.799"/>
          </svg>
          Detected Windows (x64)
        `;
        osTitle.textContent = 'BitChat for Windows';
      } else if (os === 'linux') {
        osBadge.innerHTML = `
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect>
            <line x1="8" y1="21" x2="16" y2="21"></line>
            <line x1="12" y1="17" x2="12" y2="21"></line>
          </svg>
          Detected Linux (x86_64)
        `;
        osTitle.textContent = 'BitChat for Linux';
      } else if (os === 'macos') {
        osBadge.innerHTML = `
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm1 14.5a2.5 2.5 0 0 1-5 0V8a2.5 2.5 0 0 1 5 0z"/>
          </svg>
          Detected macOS
        `;
        osTitle.textContent = 'BitChat for macOS (Source / uv)';
      }
    }

    // Platform Filter Tabs
    const filterTabs = document.querySelectorAll('.filter-tab');
    const tableRows = document.querySelectorAll('.package-table tbody tr');

    filterTabs.forEach(tab => {
      tab.addEventListener('click', function () {
        filterTabs.forEach(t => t.classList.remove('active'));
        this.classList.add('active');

        const filter = this.getAttribute('data-filter');

        tableRows.forEach(row => {
          const rowPlatform = row.getAttribute('data-platform');
          if (filter === 'all' || rowPlatform === filter) {
            row.style.display = '';
          } else {
            row.style.display = 'none';
          }
        });
      });
    });

    // Quick Search / Filter Input
    const searchInput = document.getElementById('pkg-search');
    if (searchInput) {
      searchInput.addEventListener('input', function () {
        const query = this.value.toLowerCase().trim();
        tableRows.forEach(row => {
          const text = row.textContent.toLowerCase();
          if (text.includes(query)) {
            row.style.display = '';
          } else {
            row.style.display = 'none';
          }
        });
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initDownloadExperience);
  } else {
    initDownloadExperience();
  }
})();
