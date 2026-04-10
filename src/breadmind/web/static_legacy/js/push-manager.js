/**
 * BreadMind Push Notification Manager
 * Handles push permission, subscription, and server communication.
 */
(function() {
  'use strict';

  var pushState = {
    supported: 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window,
    subscribed: false,
    permission: typeof Notification !== 'undefined' ? Notification.permission : 'denied',
  };

  /**
   * Request notification permission and subscribe to push.
   * Only call this in response to a user action (button click).
   * @returns {Promise<boolean>}
   */
  async function requestPushPermission() {
    if (!pushState.supported) {
      console.warn('[Push] Push notifications not supported');
      return false;
    }

    try {
      var permission = await Notification.requestPermission();
      pushState.permission = permission;

      if (permission !== 'granted') {
        console.log('[Push] Permission denied');
        return false;
      }

      return await subscribeToPush();
    } catch (err) {
      console.error('[Push] Error requesting permission:', err);
      return false;
    }
  }

  /**
   * Subscribe to push via PushManager and send subscription to backend.
   */
  async function subscribeToPush() {
    try {
      var registration = await navigator.serviceWorker.ready;

      // Get VAPID public key from server
      var resp = await fetch('/api/push/vapid-key');
      if (!resp.ok) return false;
      var data = await resp.json();
      var vapidKey = urlBase64ToUint8Array(data.publicKey);

      var subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: vapidKey,
      });

      // Send subscription to backend
      var subResp = await fetch('/api/push/subscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(subscription.toJSON()),
      });

      if (subResp.ok) {
        pushState.subscribed = true;
        console.log('[Push] Subscribed successfully');
        return true;
      }
      return false;
    } catch (err) {
      console.error('[Push] Subscription error:', err);
      return false;
    }
  }

  /**
   * Unsubscribe from push notifications.
   */
  async function unsubscribePush() {
    try {
      var registration = await navigator.serviceWorker.ready;
      var subscription = await registration.pushManager.getSubscription();
      if (subscription) {
        // Notify backend
        await fetch('/api/push/subscribe', {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ endpoint: subscription.endpoint }),
        });
        await subscription.unsubscribe();
      }
      pushState.subscribed = false;
      console.log('[Push] Unsubscribed');
      return true;
    } catch (err) {
      console.error('[Push] Unsubscribe error:', err);
      return false;
    }
  }

  /**
   * Check current push subscription state.
   */
  async function checkPushState() {
    if (!pushState.supported) return;
    try {
      var registration = await navigator.serviceWorker.ready;
      var subscription = await registration.pushManager.getSubscription();
      pushState.subscribed = !!subscription;
      pushState.permission = Notification.permission;
    } catch (e) {
      // Ignore
    }
  }

  /**
   * Convert URL-safe base64 to Uint8Array (for applicationServerKey).
   */
  function urlBase64ToUint8Array(base64String) {
    var padding = '='.repeat((4 - base64String.length % 4) % 4);
    var base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    var rawData = atob(base64);
    var outputArray = new Uint8Array(rawData.length);
    for (var i = 0; i < rawData.length; i++) {
      outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
  }

  // Check state on load
  if (pushState.supported) {
    window.addEventListener('load', function() {
      checkPushState();
    });
  }

  // Expose API
  window.BreadMindPush = {
    requestPermission: requestPushPermission,
    unsubscribe: unsubscribePush,
    getState: function() { return Object.assign({}, pushState); },
    checkState: checkPushState,
  };
})();
