# JSON-LD Structured Data Schema

The Christian Library Project uses JSON-LD (JSON for Linked Data) to provide structured information to search engines. This allows for rich snippets in search results.

## Model Field
The `ContentItem` model features a `structured_data` field using Django's `JSONField`.
- **Database Backend:** PostgreSQL JSONB (in production) or SQLite JSON (in development).
- **Format:** Native JSON Object (not a string).

## Automatic Synchronization
A `ContentItem.sync_structured_data()` method is called automatically on every `save()` (unless restricted by `update_fields`).
This method ensures the following fields are always in sync with the model:
- `@context`: Always set to `https://schema.org`.
- `@type`: Set based on content type (`VideoObject`, `AudioObject`, `Book`, or `CreativeWork`).
- `name`: Always synced with `get_title()`.
- `description`: Synced with the first 300 characters of the Arabic (fallback English) description.
- `inLanguage`: Array containing `ar` and/or `en` based on populated titles/descriptions.
- `url`: The canonical URL of the content item.

## AI Generation
The Gemini AI services (`GeminiSEOService`) generate more detailed structured data which is then merged into this field. The AI-generated data includes fields like:
- `author`
- `datePublished`
- `genre`
- `educationalLevel` (for Coptic Heritage)

## Examples

### Video Content
```json
{
  "@context": "https://schema.org",
  "@type": "VideoObject",
  "name": "Introduction to Coptic Liturgy",
  "description": "A detailed explanation of the Coptic Orthodox Liturgy...",
  "inLanguage": ["ar", "en"],
  "url": "https://library.coptic.church/content/uuid-here/"
}
```

### PDF (Book) Content
```json
{
  "@context": "https://schema.org",
  "@type": "Book",
  "name": "The Sayings of the Desert Fathers",
  "description": "Extracted text and analysis of the Apophthegmata Patrum...",
  "inLanguage": ["ar"],
  "url": "https://library.coptic.church/content/uuid-here/",
  "author": {
    "@type": "Person",
    "name": "Early Church Fathers"
  }
}
```

## Admin Interaction
- **Validation:** The Django Admin validates that any manual edits to `structured_data` are valid JSON.
- **Display:** JSON is pretty-printed in the admin form for easier reading.
- **Feedback:** If the AI fails to generate schema or if it's invalid, the system falls back to a minimal valid schema based on model fields.
