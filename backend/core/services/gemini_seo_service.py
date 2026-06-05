"""
Gemini AI Service for SEO Generation
Handles SEO metadata generation using Google Gemini API with Google-optimized prompts.
Uses Gemini 3 Flash for highest quality SEO generation.
"""
import logging
from typing import Dict, Tuple
from .gemini_base_service import BaseGeminiService

logger = logging.getLogger(__name__)


class GeminiSEOService(BaseGeminiService):
    """Service for generating SEO metadata using Gemini 3 Flash"""
    
    def __init__(self):
        """Initialize with DB-configured default model"""
        super().__init__()
    
    def generate_seo(
        self,
        file_path: str,
        content_type: str,
        context_text: str = None,
    ) -> Tuple[bool, Dict]:
        """
        Generate SEO metadata for uploaded file using Gemini AI
        
        Args:
            file_path: Path to the uploaded file
            content_type: Type of content ('video', 'audio', 'pdf')
            context_text: Optional extracted text to analyze instead of the raw file
            
        Returns:
            Tuple of (success: bool, seo_data: dict)
            SEO data follows standardized JSON format:
            {
                "en": {
                    "meta_title": "...",
                    "description": "...",
                    "keywords": [...],
                    "structured_data": {...}
                },
                "ar": {
                    "meta_title": "...",
                    "description": "...",
                    "keywords": [...],
                    "structured_data": {...}
                }
            }
        """
        if not self.is_available():
            return False, {"error": "Gemini AI service not available"}
            
        uploaded_file = None
        try:
            text_content = None
            if context_text and context_text.strip():
                text_content = context_text.strip()
                logger.info(
                    "Using extracted context text for SEO generation (%s, %d chars)",
                    content_type,
                    len(text_content),
                )
            else:
                # Upload file to Gemini Files API
                uploaded_file = self._upload_file(file_path)
            
            # Create SEO prompt
            prompt = self._create_seo_prompt(content_type)
            
            # Define response schema with structured data
            response_schema = {
                "type": "object",
                "properties": {
                    "en": {
                        "type": "object",
                        "properties": {
                            "meta_title": {"type": "string"},
                            "description": {"type": "string"},
                            "keywords": {
                                "type": "array",
                                "items": {"type": "string"},
                                "maxItems": 12
                            },
                            "structured_data": {
                                "type": "object",
                                "properties": {
                                    "@context": {"type": "string"},
                                    "@type": {"type": "string"},
                                    "name": {"type": "string"},
                                    "description": {"type": "string"},
                                    "inLanguage": {"type": "string"}
                                },
                                "required": ["@context", "@type", "name", "description"]
                            }
                        },
                        "required": ["meta_title", "description", "keywords", "structured_data"]
                    },
                    "ar": {
                        "type": "object",
                        "properties": {
                            "meta_title": {"type": "string"},
                            "description": {"type": "string"},
                            "keywords": {
                                "type": "array",
                                "items": {"type": "string"},
                                "maxItems": 12
                            },
                            "structured_data": {
                                "type": "object",
                                "properties": {
                                    "@context": {"type": "string"},
                                    "@type": {"type": "string"},
                                    "name": {"type": "string"},
                                    "description": {"type": "string"},
                                    "inLanguage": {"type": "string"}
                                },
                                "required": ["@context", "@type", "name", "description"]
                            }
                        },
                        "required": ["meta_title", "description", "keywords", "structured_data"]
                    },
                    "transcript": {"type": "string"},
                    "notes": {"type": "string"}
                },
                "required": ["en", "ar", "transcript", "notes"]
            }
            
            # Generate content with Gemini
            seo_data = self._generate_content(
                prompt,
                uploaded_file,
                response_schema,
                system_instruction=prompt,
                cache_key=f"seo:{self.default_model}:{content_type}",
                text_content=text_content,
            )
            
            # Validate and clean response
            cleaned_seo = self._validate_seo(seo_data)
            
            logger.info(f"Successfully generated SEO metadata for {content_type} file")
            return True, cleaned_seo
            
        except Exception as e:
            logger.error(f"Error generating SEO metadata: {e}")
            return False, {"error": f"AI generation failed: {str(e)}"}
        finally:
            if uploaded_file is not None:
                self._cleanup_file(uploaded_file)

    def generate_combined(
        self,
        file_path: str,
        content_type: str,
        context_text: str = None,
    ) -> Tuple[bool, Dict]:
        """
        Generate combined metadata + SEO output in a single Gemini call.

        Returns:
            Tuple of (success: bool, combined_data: dict)
        """
        if not self.is_available():
            return False, {"error": "Gemini AI service not available"}

        uploaded_file = None
        try:
            text_content = None
            if context_text and context_text.strip():
                text_content = context_text.strip()
                logger.info(
                    "Using extracted context text for combined Gemini generation (%s, %d chars)",
                    content_type,
                    len(text_content),
                )
            else:
                uploaded_file = self._upload_file(file_path)

            prompt = self._create_combined_prompt(content_type)
            response_schema = {
                "type": "object",
                "properties": {
                    "en": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                                "maxItems": 6,
                            },
                            "meta_title": {"type": "string"},
                            "seo_description": {"type": "string"},
                            "keywords": {
                                "type": "array",
                                "items": {"type": "string"},
                                "maxItems": 12,
                            },
                            "structured_data": {
                                "type": "object",
                                "properties": {
                                    "@context": {"type": "string"},
                                    "@type": {"type": "string"},
                                    "name": {"type": "string"},
                                    "description": {"type": "string"},
                                    "inLanguage": {"type": "string"},
                                },
                                "required": ["@context", "@type", "name", "description"],
                            },
                        },
                        "required": ["title", "description", "tags", "meta_title", "seo_description", "keywords", "structured_data"],
                    },
                    "ar": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                                "maxItems": 6,
                            },
                            "meta_title": {"type": "string"},
                            "seo_description": {"type": "string"},
                            "keywords": {
                                "type": "array",
                                "items": {"type": "string"},
                                "maxItems": 12,
                            },
                            "structured_data": {
                                "type": "object",
                                "properties": {
                                    "@context": {"type": "string"},
                                    "@type": {"type": "string"},
                                    "name": {"type": "string"},
                                    "description": {"type": "string"},
                                    "inLanguage": {"type": "string"},
                                },
                                "required": ["@context", "@type", "name", "description"],
                            },
                        },
                        "required": ["title", "description", "tags", "meta_title", "seo_description", "keywords", "structured_data"],
                    },
                    "transcript": {"type": "string"},
                    "notes": {"type": "string"},
                    "seo_title_suggestions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 3,
                    },
                },
                "required": ["en", "ar", "transcript", "notes"],
            }

            combined_data = self._generate_content(
                prompt,
                uploaded_file,
                response_schema,
                system_instruction=prompt,
                cache_key=f"combined:{self.default_model}:{content_type}",
                text_content=text_content,
            )

            cleaned_combined = self._validate_combined(combined_data)
            logger.info(f"Successfully generated combined metadata + SEO for {content_type} file")
            return True, cleaned_combined

        except Exception as e:
            logger.error(f"Error generating combined Gemini output: {e}")
            return False, {"error": f"AI generation failed: {str(e)}"}
        finally:
            if uploaded_file is not None:
                self._cleanup_file(uploaded_file)
    
    def _create_seo_prompt(self, content_type: str) -> str:
        """
        Create SEO generation prompt with Google optimization.
        
        Phase 2 Enhancement: Includes concrete examples and strict character enforcement.
        Reference: https://developers.google.com/search/docs/fundamentals/seo-starter-guide
        """
        
        content_type_map = {
            'video': 'sermon, hymn, or teaching video',
            'audio': 'sermon, hymn, prayer, or teaching recording',
            'pdf': 'book, article, or teaching document'
        }
        
        # Media type for title formatting (Phase 1 requirement)
        media_type_map = {
            'video': {'en': 'Video', 'ar': 'فيديو'},
            'audio': {'en': 'Audio', 'ar': 'صوت'},
            'pdf': {'en': 'PDF Book', 'ar': 'كتاب PDF'}
        }
        
        content_description = content_type_map.get(content_type, 'content')
        media_type_en = media_type_map.get(content_type, {}).get('en', 'Content')
        media_type_ar = media_type_map.get(content_type, {}).get('ar', 'محتوى')
        
        return f"""You are creating SEO metadata for a {content_description} in the Christian Coptic Orthodox Church of Egypt library.

CONTEXT AND NICHE CONSTRAINT:
This content library exclusively serves the Christian Coptic Orthodox Church of Egypt community. All SEO metadata MUST:
- Focus on Coptic Orthodox theology, liturgy, saints, and traditions
- Target search queries from Egyptian Coptic Christians and those interested in Oriental Orthodox Christianity
- Use terminology specific to Coptic Orthodox practice (e.g., "Divine Liturgy", "Agpeya", "Coptic saints")
- Prioritize topical authority in Coptic Christian religious education

GOOGLE SEO REQUIREMENTS - STRICT CHARACTER LIMITS:

1. Meta Title: EXACTLY 50-60 characters (Google displays ~60 chars max)
   
   REQUIRED FORMAT: "{{Content Title}} | {media_type_en} | Anba Abraam Library"
   - If content title is too long, truncate it to fit the format
   - Front-load important words
   - Include primary keyword in content title portion
   
   ✅ EXCELLENT EXAMPLES (Study These):
   
   EN (58 chars): "Divine Liturgy Explained | Video | Anba Abraam Library"
   AR (54 chars): "شرح القداس الإلهي | فيديو | مكتبة الأنبا أبرآم"
   
   EN (59 chars): "Prayer of Agpeya Guide | Audio | Anba Abraam Library"
   AR (56 chars): "دليل صلاة الأجبية | صوت | مكتبة الأنبا أبرآم"
   
   ❌ BAD EXAMPLES (Never Do This):
   
   "Anba Abraam teaches about Divine Liturgy in video" (too long - 72 chars, missing format)
   "Divine Liturgy" (too short - 14 chars, missing media type and site)
   "Divine Liturgy - Video - Christian Library" (wrong separator, wrong site name)

2. Meta Description: EXACTLY 150-160 characters (Google displays ~155-160 chars)
   
   REQUIRED FORMULA: {{Action}} "{{Title}}" by Bishop Anba Abraam. {{Value Prop}}. Free {{media_type}}.
   
   Where:
   - Action = Watch/Listen/Download (based on media type)
   - Value Prop = "The largest official collection of Coptic Orthodox teachings" or similar
   
   ✅ EXCELLENT EXAMPLES:
   
   EN (158 chars): "Watch 'Divine Liturgy Explained' by Bishop Anba Abraam. The largest official collection of Coptic Orthodox teachings. Free spiritual videos."
   
   AR (159 chars): "شاهد 'شرح القداس الإلهي' للأنبا أبرآم. أكبر مجموعة رسمية لتعاليم الكنيسة القبطية الأرثوذكسية. فيديوهات روحية مجانية."
   
   EN (157 chars): "Listen to 'Prayer of Agpeya Guide' by Bishop Anba Abraam. Access authentic Coptic Orthodox spiritual content. Free audio recordings."
   
   ❌ BAD EXAMPLES:
   
   "A video about Divine Liturgy" (too short - 28 chars, no author, no value)
   "This comprehensive video lecture series explores the deep theological and historical significance of the Divine Liturgy in the Coptic Orthodox tradition, presented by His Grace Bishop Anba Abraam" (way too long - 195 chars)
   "Divine Liturgy video by Anba Abraam" (too short, missing value proposition)

3. Keywords: 8-12 high-value keywords per language
   - Mix of head terms (high volume) and long-tail phrases
   - Include Coptic Orthodox specific terms
   - Consider search intent (informational, educational, devotional)
   
   Examples:
   EN: "Coptic Orthodox liturgy", "Divine Liturgy explained", "St. Mark teachings", "Egyptian Christian prayers", "Coptic saints", "Anba Abraam sermons"
   AR: "القداس الإلهي", "الكنيسة القبطية", "تعاليم الأنبا أبرآم", "صلوات قبطية", "الأرثوذكسية القبطية"

4. Structured Data (JSON-LD): Generate Schema.org markup for rich results
   - Use @type: "VideoObject" for videos, "AudioObject" for audio, "Article" or "Book" for PDFs
   - Include name, description, and inLanguage
   - Ensure valid Schema.org format for Google rich results

CHARACTER COUNT VALIDATION - CRITICAL:
- Count every character including spaces
- EN meta_title: Must be 50-60 chars (not 49, not 61)
- AR meta_title: Must be 50-60 chars
- EN description: Must be 150-160 chars (not 149, not 161)
- AR description: Must be 150-160 chars
- If you generate 61 chars, Google will truncate with "..." - this looks unprofessional
- If you generate 149 chars, you're wasting valuable search result space

MEDIA TYPE FOR THIS CONTENT: {media_type_en} (EN) / {media_type_ar} (AR)
Use these exact strings in the title format.

KEYWORD STRATEGY:
- Prioritize keywords with high search volume in Coptic Orthodox context
- Use natural language that matches how people search
- Include Arabic transliterations where appropriate (e.g., "Agpeya", "Tasbeha")
- Consider both local (Egypt) and diaspora (US, Canada, Australia) search patterns

THEOLOGICAL ACCURACY:
- Ensure all SEO content reflects accurate Coptic Orthodox theology
- Reference specific liturgical seasons, feasts, or saints when applicable
- Use proper Coptic Orthodox terminology

Return SEO metadata in the following JSON format:
{{
  "en": {{
    "meta_title": "Content Title | {media_type_en} | Anba Abraam Library",
    "description": "Action 'Title' by Bishop Anba Abraam. Value proposition. Free {media_type_en.lower()}.",
    "keywords": ["keyword1", "keyword2", "...", "keyword8-12"],
    "structured_data": {{
      "@context": "https://schema.org",
      "@type": "VideoObject",
      "name": "Title",
      "description": "Description",
      "inLanguage": "en"
    }}
  }},
  "ar": {{
    "meta_title": "عنوان المحتوى | {media_type_ar} | مكتبة الأنبا أبرآم",
    "description": "فعل 'العنوان' للأنبا أبرآم. القيمة المضافة. {media_type_ar} مجاني.",
    "keywords": ["كلمة1", "كلمة2", "...", "كلمة8-12"],
    "structured_data": {{
      "@context": "https://schema.org",
      "@type": "VideoObject",
      "name": "العنوان",
      "description": "الوصف",
      "inLanguage": "ar"
    }}
  }},
  "transcript": "Full transcript or detailed content summary (Arabic)",
  "notes": "Contextual study notes and historical background (Arabic)"
}}

FINAL REMINDER: Count your characters carefully. 50-60 for titles, 150-160 for descriptions. No exceptions."""

    def _create_combined_prompt(self, content_type: str) -> str:
        """Create a single prompt that returns metadata and SEO together."""

        content_type_map = {
            'video': 'sermon, hymn, or teaching video',
            'audio': 'sermon, hymn, prayer, or teaching recording',
            'pdf': 'book, article, or teaching document'
        }

        media_type_map = {
            'video': {'en': 'Video',    'ar': 'فيديو'},
            'audio': {'en': 'Audio',    'ar': 'صوت'},
            'pdf':   {'en': 'PDF Book', 'ar': 'كتاب PDF'}
        }

        # FIX 4 — schema type per content_type instead of always VideoObject
        schema_type_map = {
            'video': 'VideoObject',
            'audio': 'AudioObject',
            'pdf':   'Book'
        }

        content_description = content_type_map.get(content_type, 'content')
        media_type_en  = media_type_map.get(content_type, {}).get('en', 'Content')
        media_type_ar  = media_type_map.get(content_type, {}).get('ar', 'محتوى')
        schema_type    = schema_type_map.get(content_type, 'CreativeWork')

        return f"""You are generating ONE combined JSON response for the Christian Coptic Orthodox Church of Egypt digital library.

The source item is a {content_description}.
Media format labels:
- English: {media_type_en}
- Arabic: {media_type_ar}
Schema.org type to use: {schema_type}

=== MISSION ===
    Return a single JSON object satisfying two distinct purposes simultaneously:
1. Content metadata — for library browsing, filtering, and internal categorization.
2. SEO metadata — for search engine indexing and Schema.org rich results.
These are NOT the same fields rephrased. They serve different audiences with different length and tone requirements.

=== NICHE CONSTRAINTS ===
Every word of output must be grounded in the Christian Coptic Orthodox Church of Egypt tradition:
- Theology, liturgy, saints, feasts, sacraments, and Coptic heritage only.
- Appropriate for church education, worship, devotional use, and public library search.
- Clear and natural — never generic marketing language.
- Reject vague general-Christian phrasing that weakens the Orthodox context.

=== FIELD DEFINITIONS ===
| Field                  | Purpose                                              |
|------------------------|------------------------------------------------------|
| title                  | Human-readable library title for catalog display     |
| description            | Content summary for catalog browsing                 |
| tags                   | Short category labels for browse/filter UI           |
| meta_title             | SEO title shown in Google search results             |
| seo_description        | SEO snippet shown under the meta_title in results    |
| keywords               | SEO keyword list for search engine indexing          |
| structured_data        | Schema.org JSON-LD payload ({schema_type})           |
| transcript             | Detailed Arabic summary or transcript of the content |
| notes                  | Arabic contextual, historical, or theological notes  |
| seo_title_suggestions  | Alternate SEO title candidates for A/B testing       |

=== LENGTH RULES — HARD LIMITS ===
Estimate character count before writing each field. Adjust until within range.

English fields:
- title:           ≤ 100 characters
- description:     ≤ 200 characters
- meta_title:      50–60 characters (target center; never below 48 or above 62)
- seo_description: 150–160 characters (target center; never below 148 or above 162)
- tags:            3–6 items, each 1–4 words
- keywords:        8–12 items

Arabic fields (Arabic script is denser; adjust targets slightly):
- title:           ≤ 80 characters
- description:     ≤ 160 characters
- meta_title:      45–60 characters
- seo_description: 140–160 characters
- tags:            3–6 items
- keywords:        8–12 items

Supporting fields:
- transcript:      300–800 words in Arabic; full summary or verbatim key sections
- notes:           100–400 words in Arabic; theological, historical, or contextual commentary
- seo_title_suggestions: exactly 3 items in English AND 3 items in Arabic, each 50–60 characters

=== CONTENT METADATA RULES ===
- Read the actual content carefully before writing any title or description.
- Titles must be specific and accurate — no filler words like "important" or "special".
- Descriptions must explain what the item is about AND why it matters to this audience.
- Tags must be short, browsable labels: single words or short phrases such as:
  liturgy, hymns, St. George, baptism, pascha, kiahk, deacon, anaphora, tasbeha
- Use language fitting for church members, theological students, and researchers.

=== SEO RULES ===
- meta_title: front-load the core subject; include the media type label ({media_type_en} / {media_type_ar}) when it aids clarity; avoid clickbait.
- seo_description: complete sentence(s); include a Coptic Orthodox context signal; end with natural closure, not a truncation.
- keywords: prefer multi-word phrases over single words; prioritize terms people actually search (e.g. "Coptic Orthodox hymns", "St. Shenouda sermons", "deacon liturgy training").
- structured_data: must be valid Schema.org JSON-LD using @type: "{schema_type}"; include name, description, and inLanguage at minimum.

=== TAGS RULE (updated) ===
- Generate 3–6 tags spanning at least 3 different dimensions from the COVERAGE MANDATE table.
- Apply SEMANTIC DIFF CHECK and TITLE ECHO CHECK before finalizing.
- Each tag must be a browsable label a user would click to find similar items —
  not a description of this specific item.

=== KEYWORDS RULE (updated) ===
- Generate 8–12 keywords spanning at least 5 different dimensions from the COVERAGE MANDATE table.
- Apply SEMANTIC DIFF CHECK and SYNONYM BAN before finalizing.
- Prefer multi-word phrases (2–4 words) over single words — they match real search queries.
- At least 2 keywords must reflect search intent (what someone types when looking for this).
- At least 1 keyword must include the media format: "Coptic Orthodox {media_type_en}".

=== seo_title_suggestions RULE (updated) ===
- Write 3 suggestions per language.
- Each must lead with a DIFFERENT subject (saint, feast, audience, content form, or topic).
- Apply the seo_title_suggestions DIFF CHECK before finalizing.
- All must stay within 50–60 characters (English) and 45–60 characters (Arabic).

=== FALLBACK RULES ===
- If meta_title cannot be made meaningfully different from title within character limits, use a shortened version of the title with the media format label appended.
- If seo_description has no natural 150-character ending, extend with an audience-targeting phrase such as "for Coptic Orthodox worshippers and students."
- If content is unclear or minimal, generate fields based on topic area and content type — do not leave any field empty or null.

=== THEOLOGICAL ACCURACY ===
- Only reference specific Coptic saints, liturgies, feasts, and texts when they genuinely apply to the content.
- Use correct Coptic Orthodox terminology (e.g. Agpeya, Anaphora of St. Basil, Kiahk, Pascha, Pope Shenouda III).
- Never blend denominations. Never use Protestant or Roman Catholic framing.

=== FIELD UNIQUENESS CONTRACT ===
Before finalizing any array field (tags, keywords, seo_title_suggestions), run this
internal check on every item you have drafted:

  1. SEMANTIC DIFF CHECK — Read each pair of items in the array.
     If two items share the same root meaning, even with different words or word order,
     delete the weaker one and replace it with a genuinely different concept.
     Examples of what to REJECT:
       ❌ ["Coptic hymns", "Coptic chants", "Orthodox hymns"]   → 3 items, 1 concept
       ❌ ["St. Shenouda", "Pope Shenouda", "Shenouda III"]     → 3 items, 1 person
       ❌ ["baptism", "baptismal rite", "rite of baptism"]      → 3 items, 1 topic
     What to DO instead — each item must cover a different dimension:
       ✅ ["Coptic hymns", "deacon ordination", "Kiahk season"] → 3 distinct concepts

  2. TITLE ECHO CHECK — No tag, keyword, or suggestion may be a
     substring or paraphrase of the library title or meta_title.
     The title is already displayed — repeating it as a tag adds zero value.
     If you catch yourself doing this, replace with an adjacent topic or audience term.

  3. SYNONYM BAN — Synonyms are NOT distinct items.
     "Prayer" and "supplication" are the same concept. Pick one; use the other slot
     for a concept not yet covered anywhere in the output.

  4. COVERAGE MANDATE — After deduplication, each array must span
     multiple distinct dimensions. Use this dimension map as a guide:

     For TAGS (pick from different rows, not the same row twice):
       | Dimension       | Examples                                      |
       |-----------------|-----------------------------------------------|
       | Topic/theme     | pascha, baptism, fasting, resurrection        |
       | Liturgical role | deacon, priest, cantor, congregation          |
       | Time/season     | Kiahk, Holy Week, Advent, feast day           |
       | Saint/figure    | St. George, St. Mary, St. Shenouda            |
       | Content form    | hymn, sermon, commentary, prayer, reading     |
       | Audience        | youth, Sunday school, monastics, seminarians  |

     For KEYWORDS (pick from different rows):
       | Dimension       | Examples                                      |
       |-----------------|-----------------------------------------------|
       | Entity          | "Pope Shenouda III sermons", "St. Mina miracles" |
       | Liturgy term    | "Agpeya prayers", "Anaphora of St. Basil"    |
       | Search intent   | "learn Coptic liturgy", "Coptic hymns download" |
       | Season/feast    | "Coptic Easter hymns", "Kiahk tasbeha"       |
       | Audience need   | "deacon training", "Sunday school Coptic"    |
       | Format signal   | "Coptic Orthodox audio", "Coptic sermon PDF" |

  5. seo_title_suggestions DIFF CHECK — Each of the 3 suggestions must
     use a meaningfully different angle, not just swap one adjective:
       ❌ "Coptic Hymns Video | Orthodox Liturgy"
          "Coptic Orthodox Hymns | Liturgy Video"
          "Orthodox Coptic Hymns Video | Liturgy"     → same structure, rotated words
       ✅ Angle 1 — lead with the saint or feast:     "St. George Feast Hymns – Coptic Video"
          Angle 2 — lead with the audience need:      "Learn Coptic Liturgy Hymns | Full Video"
          Angle 3 — lead with the content form:       "Coptic Deacon Hymns Training | Orthodox"

=== OUTPUT RULES ===
- Return ONLY valid JSON. No markdown fences, no commentary, no text outside the JSON.
- Every field in the schema must be populated.
- Validate that meta_title and seo_description character counts fall within range before finalizing.

Return JSON in this exact format:
{{
    "en": {{
        "title": "English library title (≤100 chars)",
        "description": "English catalog description (≤200 chars)",
        "tags": ["tag1", "tag2", "tag3"],
        "meta_title": "English SEO title (50-60 chars)",
        "seo_description": "English SEO description (150-160 chars)",
        "keywords": ["keyword1", "keyword2", "keyword3"],
        "structured_data": {{
            "@context": "https://schema.org",
            "@type": "{schema_type}",
            "name": "Title matching meta_title",
            "description": "Description matching seo_description",
            "inLanguage": "en"
        }},
        "seo_title_suggestions": ["Alt EN title 1", "Alt EN title 2", "Alt EN title 3"]
    }},
    "ar": {{
        "title": "Arabic library title (≤80 chars)",
        "description": "Arabic catalog description (≤160 chars)",
        "tags": ["وسم1", "وسم2", "وسم3"],
        "meta_title": "Arabic SEO title (45-60 chars)",
        "seo_description": "Arabic SEO description (140-160 chars)",
        "keywords": ["كلمة1", "كلمة2", "كلمة3"],
        "structured_data": {{
            "@context": "https://schema.org",
            "@type": "{schema_type}",
            "name": "العنوان",
            "description": "الوصف",
            "inLanguage": "ar"
        }},
        "seo_title_suggestions": ["بديل عربي 1", "بديل عربي 2", "بديل عربي 3"]
    }},
    "transcript": "Arabic transcript or detailed content summary (300-800 words)",
    "notes": "Arabic contextual, historical, or theological notes (100-400 words)"
}}"""
    
    def _validate_seo(self, seo_data: Dict) -> Dict:
        """
        Validate and clean SEO metadata with strict character limit enforcement.
        
        Phase 2 Enhancement: Adds warning logs for quality control and debugging.
        Enforces Google's best practices for title and description lengths.
        """
        cleaned = {
            'transcript': str(seo_data.get('transcript', '')).strip(),
            'notes': str(seo_data.get('notes', '')).strip()
        }
        
        for lang in ['en', 'ar']:
            if lang in seo_data:
                lang_data = seo_data[lang]
                
                # Validate meta_title with strict length checking
                meta_title = str(lang_data.get('meta_title', '')).strip()
                title_len = len(meta_title)
                
                if title_len > 60:
                    logger.warning(
                        f"[{lang.upper()}] Meta title TOO LONG ({title_len} chars, max 60): "
                        f"{meta_title[:70]}..."
                    )
                    meta_title = meta_title[:60]  # Hard truncate
                elif title_len < 50:
                    logger.warning(
                        f"[{lang.upper()}] Meta title TOO SHORT ({title_len} chars, min 50): "
                        f"{meta_title}"
                    )
                elif 50 <= title_len <= 60:
                    logger.info(
                        f"[{lang.upper()}] ✓ Meta title perfect length ({title_len} chars): "
                        f"{meta_title}"
                    )
                
                # Validate description with strict length checking
                description = str(lang_data.get('description', '')).strip()
                desc_len = len(description)
                
                if desc_len > 160:
                    logger.warning(
                        f"[{lang.upper()}] Description TOO LONG ({desc_len} chars, max 160): "
                        f"{description[:70]}..."
                    )
                    description = description[:160]  # Hard truncate
                elif desc_len < 150:
                    logger.warning(
                        f"[{lang.upper()}] Description TOO SHORT ({desc_len} chars, min 150): "
                        f"{description[:70]}..."
                    )
                elif 150 <= desc_len <= 160:
                    logger.info(
                        f"[{lang.upper()}] ✓ Description perfect length ({desc_len} chars)"
                    )
                
                # Validate and clean keywords
                keywords = lang_data.get('keywords', [])
                if isinstance(keywords, list):
                    # Limit to 12 keywords, each max 50 chars
                    keywords = [str(k)[:50].strip() for k in keywords[:12] if k]
                    keyword_count = len(keywords)
                    
                    if keyword_count < 8:
                        logger.warning(
                            f"[{lang.upper()}] Too few keywords ({keyword_count}, target 8-12)"
                        )
                    elif keyword_count > 12:
                        logger.warning(
                            f"[{lang.upper()}] Too many keywords ({keyword_count}, truncated to 12)"
                        )
                    else:
                        logger.info(
                            f"[{lang.upper()}] ✓ Keyword count optimal ({keyword_count} keywords)"
                        )
                else:
                    logger.error(f"[{lang.upper()}] Keywords not a list, defaulting to empty")
                    keywords = []
                
                # Validate structured data
                structured_data = lang_data.get('structured_data', {})
                if not isinstance(structured_data, dict):
                    logger.error(f"[{lang.upper()}] Structured data not a dict, defaulting to empty")
                    structured_data = {}
                elif '@type' not in structured_data:
                    logger.warning(f"[{lang.upper()}] Structured data missing @type")
                else:
                    logger.info(
                        f"[{lang.upper()}] ✓ Structured data present (@type: {structured_data.get('@type')})"
                    )
                
                cleaned[lang] = {
                    'meta_title': meta_title,
                    'description': description,
                    'keywords': keywords,
                    'structured_data': structured_data
                }
            else:
                logger.error(f"[{lang.upper()}] Language data missing from SEO response")
                cleaned[lang] = {
                    'meta_title': '',
                    'description': '',
                    'keywords': [],
                    'structured_data': {}
                }
        
        return cleaned

    def _validate_combined(self, combined_data: Dict) -> Dict:
        """Validate combined metadata + SEO payload."""
        cleaned = self._validate_seo(combined_data)

        for lang in ['en', 'ar']:
            lang_data = combined_data.get(lang, {}) if isinstance(combined_data, dict) else {}
            cleaned[lang] = {
                **cleaned.get(lang, {}),
                'title': str(lang_data.get('title', '')).strip()[:100],
                'description': str(lang_data.get('description', '')).strip()[:200],
                'tags': [str(tag).strip()[:50] for tag in (lang_data.get('tags', []) or [])[:6] if str(tag).strip()],
                'meta_title': str(lang_data.get('meta_title', '')).strip()[:70],
                'seo_description': str(lang_data.get('seo_description', '')).strip()[:160],
                'keywords': [str(keyword).strip()[:80] for keyword in (lang_data.get('keywords', []) or [])[:12] if str(keyword).strip()],
                'structured_data': lang_data.get('structured_data', {}),
            }

        cleaned['seo_title_suggestions'] = [
            str(title).strip()[:120]
            for title in (combined_data.get('seo_title_suggestions', []) or [])[:3]
            if str(title).strip()
        ]
        return cleaned


def get_gemini_seo_service() -> GeminiSEOService:
    """Get or create Gemini SEO service singleton"""
    if not hasattr(get_gemini_seo_service, '_instance'):
        get_gemini_seo_service._instance = GeminiSEOService()
    return get_gemini_seo_service._instance
