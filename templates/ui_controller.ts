/**
 * Контроллер плавного интерфейса Samberrrgram
 */
class SmoothUI {
    // Управляет появлением меню действий над сообщениями
    static showMessageMenu(event: MouseEvent, menuElement: HTMLElement): void {
        event.preventDefault();
        
        // Устанавливаем позицию
        menuElement.style.left = `${event.pageX}px`;
        menuElement.style.top = `${event.pageY}px`;
        
        // Активируем класс анимации
        menuElement.classList.add('active');
        
        // Закрытие при клике мимо
        const closeHandler = () => {
            menuElement.classList.remove('active');
            document.removeEventListener('click', closeHandler);
        };
        setTimeout(() => document.addEventListener('click', closeHandler), 10);
    }

    // Плавный переход между чатами (затухание старого, выезд нового)
    static async switchChatTransition(chatId: string): Promise<void> {
        const chatWindow = document.getElementById('chat-messages-container');
        if (!chatWindow) return;

        // 1. Плавное исчезновение
        chatWindow.style.transition = 'opacity 0.2s ease, transform 0.2s ease';
        chatWindow.style.opacity = '0';
        chatWindow.style.transform = 'translateX(-10px)';

        await new Promise(r => setTimeout(r, 200));

        // 2. Здесь код переключения чата в JS...
        // console.log(`Switched to ${chatId}`);

        // 3. Плавное появление
        chatWindow.style.transform = 'translateX(10px)';
        setTimeout(() => {
            chatWindow.style.opacity = '1';
            chatWindow.style.transform = 'translateX(0)';
        }, 50);
    }

    // Универсальный метод плавного показа/скрытия
    static toggleElement(elementId: string, show: boolean): void {
        const el = document.getElementById(elementId);
        if (!el) return;

        if (show) {
            el.style.display = 'flex';
            setTimeout(() => {
                el.style.transition = 'all 0.4s cubic-bezier(0.22, 1, 0.36, 1)';
                el.style.opacity = '1';
                el.style.transform = 'translateY(0) scale(1)';
            }, 10);
        } else {
            el.style.transition = 'all 0.3s cubic-bezier(0.32, 0, 0.67, 0)';
            el.style.opacity = '0';
            el.style.transform = 'translateY(10px) scale(0.95)';
            
            setTimeout(() => { el.style.display = 'none'; }, 300);
        }
    }
}

// Делаем класс доступным глобально для твоего основного JS
(window as any).SmoothUI = SmoothUI;
