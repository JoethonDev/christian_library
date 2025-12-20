from celery import shared_task
from django.apps import apps

def get_contentitem_model():
    return apps.get_model('media_manager', 'ContentItem')

@shared_task
def extract_and_index_contentitem(contentitem_id):
    ContentItem = get_contentitem_model()
    try:
        item = ContentItem.objects.get(id=contentitem_id)
        item.extract_text_from_pdf()
        item.update_search_vector()
        item.save(update_fields=["book_content", "search_vector"])
    except ContentItem.DoesNotExist:
        pass
