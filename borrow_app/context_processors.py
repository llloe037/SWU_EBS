from .models import Notification


def notifications(request):
    if not request.user.is_authenticated or request.user.is_staff:
        return {'unread_notification_count': 0, 'unread_notifications': []}
    unread = Notification.objects.filter(user=request.user, is_read=False).select_related('borrow_request')[:10]
    return {
        'unread_notification_count': unread.count(),
        'unread_notifications': list(unread),
    }
