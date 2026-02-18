(function () {
  const FLASH_ID = 'offline-flash-message';

  function ensureOverlay() {
    let overlay = document.querySelector('.message-overlay[data-offline="true"]');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.className = 'message-overlay';
      overlay.dataset.offline = 'true';
      overlay.setAttribute('role', 'status');
      overlay.setAttribute('aria-live', 'assertive');
      document.body.appendChild(overlay);
    }
    overlay.classList.remove('is-hiding');
    return overlay;
  }

  function showOfflineFlash() {
    const overlay = ensureOverlay();
    let toast = document.getElementById(FLASH_ID);
    if (!toast) {
      toast = document.createElement('div');
      toast.id = FLASH_ID;
      toast.className = 'message-toast warning';
      overlay.appendChild(toast);
    }
    toast.textContent =
      (window.TRANSLATIONS && window.TRANSLATIONS.offlineWarning) ||
      'You are offline. Please reconnect.';
  }

  function hideOfflineFlash() {
    const overlay = document.querySelector('.message-overlay[data-offline="true"]');
    if (!overlay) {
      return;
    }

    overlay.classList.add('is-hiding');
    window.setTimeout(() => {
      overlay.remove();
    }, 400);
  }

  function updateState() {
    if (navigator.onLine) {
      hideOfflineFlash();
    } else {
      showOfflineFlash();
    }
  }

  window.addEventListener('online', updateState);
  window.addEventListener('offline', updateState);
  document.addEventListener('DOMContentLoaded', updateState);
})();