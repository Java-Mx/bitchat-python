/**
 * BitChat Official Website - Core Interactivity
 * Accessible, lightweight vanilla JavaScript. Zero framework overhead.
 */

(function () {
  'use strict';

  // Mobile Navigation Toggle
  const menuBtn = document.querySelector('.mobile-menu-btn');
  const mobileNav = document.querySelector('.mobile-nav');

  if (menuBtn && mobileNav) {
    menuBtn.addEventListener('click', function () {
      const isExpanded = menuBtn.getAttribute('aria-expanded') === 'true';
      menuBtn.setAttribute('aria-expanded', !isExpanded);
      mobileNav.classList.toggle('open');
      menuBtn.setAttribute('aria-label', isExpanded ? 'Open navigation menu' : 'Close navigation menu');
    });

    // Close on Escape key
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && mobileNav.classList.contains('open')) {
        mobileNav.classList.remove('open');
        menuBtn.setAttribute('aria-expanded', 'false');
        menuBtn.focus();
      }
    });
  }

  // Active Link Highlighting
  const currentPath = window.location.pathname.split('/').pop() || 'index.html';
  const navLinks = document.querySelectorAll('.nav-links a, .mobile-nav a');

  navLinks.forEach(link => {
    const href = link.getAttribute('href');
    if (href === currentPath || (currentPath === '' && href === 'index.html')) {
      link.classList.add('active');
    }
  });

  // Universal Checksum & Code Copy functionality
  document.addEventListener('click', function (e) {
    const copyBtn = e.target.closest('.btn-copy, .btn-copy-code');
    if (!copyBtn) return;

    const targetText = copyBtn.getAttribute('data-copy');
    if (!targetText) return;

    const originalHtml = copyBtn.innerHTML;

    function reportSuccess() {
      copyBtn.classList.add('copied');
      copyBtn.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
        <span>Copied!</span>
      `;
      setTimeout(() => {
        copyBtn.classList.remove('copied');
        copyBtn.innerHTML = originalHtml;
      }, 2000);
    }

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(targetText).then(reportSuccess).catch(() => {
        fallbackCopy(targetText, reportSuccess);
      });
    } else {
      fallbackCopy(targetText, reportSuccess);
    }
  });

  function fallbackCopy(text, callback) {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    try {
      document.execCommand('copy');
      if (callback) callback();
    } catch (err) {
      console.warn('Fallback copy failed:', err);
    }
    document.body.removeChild(textarea);
  }

  // Hero Screenshot Tab Switcher
  const tabButtons = document.querySelectorAll('.terminal-tab-btn');
  const screenshotImg = document.querySelector('.terminal-screenshot');
  const screenshotCaption = document.querySelector('.screenshot-caption-text');

  if (tabButtons.length > 0 && screenshotImg) {
    tabButtons.forEach(btn => {
      btn.addEventListener('click', function () {
        tabButtons.forEach(b => b.classList.remove('active'));
        this.classList.add('active');

        const newSrc = this.getAttribute('data-img');
        const newCaption = this.getAttribute('data-caption');

        if (newSrc) {
          screenshotImg.setAttribute('src', newSrc);
          screenshotImg.setAttribute('alt', newCaption || 'BitChat Terminal UI');
        }
        if (screenshotCaption && newCaption) {
          screenshotCaption.textContent = newCaption;
        }
      });
    });
  }

  // Back to Top Button
  const backToTopBtn = document.querySelector('.back-to-top');
  if (backToTopBtn) {
    window.addEventListener('scroll', function () {
      if (window.scrollY > 400) {
        backToTopBtn.classList.add('visible');
      } else {
        backToTopBtn.classList.remove('visible');
      }
    });

    backToTopBtn.addEventListener('click', function () {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }
})();
