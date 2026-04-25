/**
 * push_notifications.js
 * Этот скрипт отвечает за подписку пользователя на Push-уведомления
 * и отправку подписки на сервер.
 */

function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding)
        .replace(/\-/g, '+')
        .replace(/_/g, '/');

    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);

    for (let i = 0; i < rawData.length; ++i) {
        outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
}

async function subscribeUserToPush() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
        console.warn('Push notifications not supported by this browser.');
        return;
    }

    try {
        const registration = await navigator.serviceWorker.ready;
        let subscription = await registration.pushManager.getSubscription();

        if (subscription) {
            console.log('Existing push subscription found:', subscription);
            // Отправляем существующую подписку на сервер, если она есть
            socket.emit('save_push_subscription', subscription.toJSON());
            return;
        }

        console.log('No existing push subscription, attempting to subscribe...');

        // Запрашиваем публичный VAPID ключ с сервера
        socket.emit('get_push_key');
        socket.on('push_key_data', async (data) => {
            const vapidPublicKey = data.public_key;
            if (!vapidPublicKey) {
                console.error('VAPID Public Key not received from server.');
                return;
            }
            const convertedVapidKey = urlBase64ToUint8Array(vapidPublicKey);

            subscription = await registration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: convertedVapidKey
            });

            console.log('New push subscription:', subscription);
            socket.emit('save_push_subscription', subscription.toJSON());
        });

    } catch (error) {
        console.error('Failed to subscribe the user to push:', error);
    }
}

// Запускаем подписку после того, как пользователь дал разрешение
Notification.requestPermission().then(permission => {
    if (permission === 'granted') {
        subscribeUserToPush();
    } else {
        console.warn('Notification permission denied.');
    }
});
