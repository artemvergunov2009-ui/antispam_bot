/**
 * Контроллер плавного интерфейса Samberrrgram
 */
class SmoothUI {
    /**
     * Плавное переключение видимости элементов (например, окон вызова)
     * Использует cubic-bezier для эффекта "не резкого" движения
     */
    static toggleElement(elementId: string, show: boolean): void {
        const el = document.getElementById(elementId);
        if (!el) return;

        if (show) {
            el.style.display = 'flex';
            el.style.opacity = '0';
            el.style.transform = 'translateY(20px) scale(0.95)';
            
            // Небольшая задержка для срабатывания transition
            setTimeout(() => {
                el.style.transition = 'all 0.5s cubic-bezier(0.22, 1, 0.36, 1)';
                el.style.opacity = '1';
                el.style.transform = 'translateY(0) scale(1)';
            }, 10);
        } else {
            el.style.transition = 'all 0.4s cubic-bezier(0.32, 0, 0.67, 0)';
            el.style.opacity = '0';
            el.style.transform = 'translateY(10px) scale(0.98)';
            
            setTimeout(() => {
                el.style.display = 'none';
            }, 400);
        }
    }

    /**
     * Добавляет плавный эффект при наведении на сообщения
     */
    static initMessageAnimations(): void {
        document.querySelectorAll('.message').forEach((msg: Element) => {
            (msg as HTMLElement).style.transition = 'transform 0.3s ease-out';
        });
    }
}
