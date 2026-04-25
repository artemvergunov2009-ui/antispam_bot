// Этот код работает в фоне телефона

self.addEventListener('push', function(event) {
    if (event.data) {
        const data = event.data.json();
        
        const options = {
            body: data.body,
            icon: data.icon || '/static/logo.png', // Твой логотип
            badge: '/static/logo.png',
            data: {
                url: data.url || '/chat' // Куда перекинуть при клике
            }
        };

        if (data.type === 'call') {
            options.vibrate = [200, 100, 200, 100, 200, 100, 200]; // Длинная вибрация для звонка
            options.requireInteraction = true; // Уведомление висит, пока юзер не нажмет или не смахнет
            options.tag = 'call'; // Группируем уведомления о звонках
            options.renotify = true; // Повторно показывать уведомление, если пришел новый звонок
        } else { // Для обычных сообщений
            options.vibrate = [200, 100, 200]; // Короткая вибрация для сообщений
            options.tag = 'message'; // Группируем уведомления о сообщениях
        }

        // Показываем само уведомление
        event.waitUntil(
            self.registration.showNotification(data.title, options)
        );
    }
});

// Что делать, когда пользователь кликает по уведомлению
self.addEventListener('notificationclick', function(event) {
    event.notification.close(); // Закрываем плашку уведомления
    
    // Открываем приложение на нужной странице (запускаем твой Samberrrgram)
    event.waitUntil(
        clients.matchAll({ type: 'window' }).then(windowClients => {
            // Если вкладка уже открыта, просто фокусируемся на ней
            for (let i = 0; i < windowClients.length; i++) {
                let client = windowClients[i];
                if (client.url.includes(event.notification.data.url) && 'focus' in client) {
                    return client.focus();
                }
            }
            // Иначе открываем новую
            if (clients.openWindow) {
                return clients.openWindow(event.notification.data.url);
            }
        })
    );
});
