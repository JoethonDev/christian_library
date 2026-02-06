"""
Gemini AI Service for Content Generation
Handles file upload and AI-powered content generation using Google Gemini API
"""
import json
import os
import tempfile
import logging
from typing import Dict, Optional, Tuple
from django.conf import settings
from google import genai

logger = logging.getLogger(__name__)


class GeminiContentGenerator:
    """Service for generating content metadata using Gemini AI"""
    
    def __init__(self):
        """Initialize Gemini client"""
        try:
            # Get API key from settings
            api_key = getattr(settings, 'GEMINI_API_KEY', None)
            if not api_key:
                raise ValueError("GEMINI_API_KEY not found in settings")
                
            # Get model from settings with optimal default
            # gemini-2.5-flash: Best price-performance, large-scale processing, multilingual, fast response
            self.model = getattr(settings, 'GEMINI_MODEL', 'gemini-3-flash-preview')
                
            # Initialize client with API key
            self.client = genai.Client(api_key=api_key)
            
        except Exception as e:
            logger.error(f"Failed to initialize Gemini client: {e}")
            self.client = None
    
    def is_available(self) -> bool:
        """Check if Gemini service is available"""
        return self.client is not None
    
    def generate_complete_metadata(self, file_path: str, content_type: str) -> Tuple[bool, Dict]:
        """
        Generate complete metadata (content + SEO) for uploaded file using Gemini AI
        
        Args:
            file_path: Path to the uploaded file
            content_type: Type of content ('video', 'audio', 'pdf')
            
        Returns:
            Tuple of (success: bool, metadata: dict)
            metadata contains: title_ar, title_en, description_ar, description_en, 
            tags, seo_keywords_ar, seo_keywords_en, seo_meta_description_ar, 
            seo_meta_description_en, seo_title_suggestions, structured_data
        """
        if not self.is_available():
            return False, {'error': 'Gemini service is not available'}
            
        try:
            # Upload file to Gemini
            uploaded_file = self.client.files.upload(file=file_path)
            
            # Create comprehensive prompt for both content and SEO metadata
            prompt = self._create_complete_metadata_prompt(content_type)
            
            # Generate content with Gemini using consistency-optimized config
            response = self.client.models.generate_content(
                model=self.model,
                contents=[prompt, uploaded_file],
                config={
                    "temperature": 0.1,  # Low temperature for deterministic outputs
                    "top_p": 0.9,       # Nucleus sampling for consistency
                    "top_k": 20,        # Limit token choices for predictability
                    "response_mime_type": "application/json",
                    "response_schema": {
                        "type": "object",
                        "properties": {
                            "title_ar": {"type": "string"},
                            "title_en": {"type": "string"},
                            "description_ar": {"type": "string"},
                            "description_en": {"type": "string"},
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                                "maxItems": 6
                            },
                            "seo_keywords_ar": {
                                "type": "array",
                                "items": {"type": "string"},
                                "maxItems": 12
                            },
                            "seo_keywords_en": {
                                "type": "array",
                                "items": {"type": "string"},
                                "maxItems": 12
                            },
                            "seo_meta_description_ar": {"type": "string"},
                            "seo_meta_description_en": {"type": "string"},
                            "seo_title_suggestions": {
                                "type": "object",
                                "properties": {
                                    "ar": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "maxItems": 3
                                    },
                                    "en": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "maxItems": 3
                                    }
                                },
                                "required": ["ar", "en"]
                            },
                            "structured_data": {
                                "type": "object",
                                "properties": {
                                    "@context": {"type": "string"},
                                    "@type": {"type": "string"},
                                    "name": {"type": "string"},
                                    "description": {"type": "string"},
                                    "inLanguage": {
                                        "type": "array",
                                        "items": {"type": "string"}
                                    }
                                },
                                "required": ["@context", "@type", "name", "description"]
                            }
                        },
                        "required": ["title_ar", "title_en", "description_ar", "description_en", 
                                   "tags", "seo_keywords_ar", "seo_keywords_en",
                                   "seo_meta_description_ar", "seo_meta_description_en",
                                   "seo_title_suggestions", "structured_data"]
                    }
                }
            )
            
            # Clean up uploaded file
            self.client.files.delete(name=uploaded_file.name)
            
            # Parse response with better error handling
            try:
                logger.info(f"Raw Gemini response length: {len(response.text)} chars")
                logger.info(f"Response preview: {response.text[:200]}...")
                
                # Check if response is empty
                if not response.text or response.text.strip() == "":
                    raise ValueError("Empty response from Gemini API")
                
                # Try to parse JSON
                metadata = json.loads(response.text)
                logger.info(f"Successfully parsed JSON with {len(metadata)} fields")
                
            except json.JSONDecodeError as e:
                logger.error(f"JSON parsing failed: {e}")
                logger.error(f"Response content: {response.text}")
                
                # Try to find where JSON starts (sometimes there might be extra text)
                response_text = response.text.strip()
                json_start = response_text.find('{')
                json_end = response_text.rfind('}') + 1
                
                if json_start != -1 and json_end > json_start:
                    try:
                        extracted_json = response_text[json_start:json_end]
                        logger.info(f"Attempting to parse extracted JSON: {extracted_json[:200]}...")
                        metadata = json.loads(extracted_json)
                        logger.info("Successfully parsed extracted JSON")
                    except json.JSONDecodeError as e2:
                        logger.error(f"Failed to parse extracted JSON: {e2}")
                        return False, {'error': f'Invalid JSON response: {str(e)}'}
                else:
                    return False, {'error': f'No valid JSON found in response: {str(e)}'}
            
            # Validate and clean metadata
            validated_metadata = self._validate_complete_metadata(metadata)
            
            return True, validated_metadata
            
        except Exception as e:
            logger.error(f"Error generating complete metadata: {str(e)}")
            return False, {'error': f'Generation failed: {str(e)}'}

    def generate_seo_metadata(self, file_path: str, content_type: str) -> Tuple[bool, Dict]:
        """
        Generate comprehensive SEO metadata for uploaded file using Gemini AI
        
        Args:
            file_path: Path to the uploaded file
            content_type: Type of content ('video', 'audio', 'pdf')
            
        Returns:
            Tuple of (success: bool, metadata: dict)
            metadata contains: title_ar, title_en, description_ar, description_en, 
            tags_ar, tags_en, seo_keywords_ar, seo_keywords_en, 
            seo_meta_description_ar, seo_meta_description_en,
            seo_title_suggestions, structured_data
        """
        if not self.is_available():
            return False, {"error": "Gemini AI service not available"}
            
        try:
            # Upload file to Gemini
            uploaded_file = self.client.files.upload(file=file_path)
            
            # Create SEO prompt
            prompt = self._create_seo_prompt(content_type)
            
            # Generate content with Gemini using consistency-optimized config
            response = self.client.models.generate_content(
                model=self.model,
                contents=[prompt, uploaded_file],
                config={
                    "temperature": 0.1,  # Low temperature for deterministic outputs
                    "top_p": 0.9,       # Nucleus sampling for consistency
                    "top_k": 20,        # Limit token choices for predictability
                    "response_mime_type": "application/json",
                    "response_schema": {
                        "type": "object",
                        "properties": {
                            "title_ar": {"type": "string"},
                            "title_en": {"type": "string"},
                            "description_ar": {"type": "string"},
                            "description_en": {"type": "string"},
                            "tags_ar": {
                                "type": "array",
                                "items": {"type": "string"},
                                "maxItems": 6
                            },
                            "tags_en": {
                                "type": "array", 
                                "items": {"type": "string"},
                                "maxItems": 6
                            },
                            "seo_keywords_ar": {
                                "type": "array",
                                "items": {"type": "string"},
                                "maxItems": 30
                            },
                            "seo_keywords_en": {
                                "type": "array",
                                "items": {"type": "string"},
                                "maxItems": 30
                            },
                            "seo_meta_description_ar": {"type": "string"},
                            "seo_meta_description_en": {"type": "string"},
                            "seo_title_ar": {"type": "string"},
                            "seo_title_en": {"type": "string"},
                            "transcript": {"type": "string"},
                            "notes": {"type": "string"},
                            "seo_title_suggestions": {
                                "type": "array",
                                "items": {"type": "string"},
                                "maxItems": 3
                            },
                            "structured_data": {
                                "type": "object",
                                "properties": {
                                    "@context": {"type": "string"},
                                    "@type": {"type": "string"},
                                    "name": {"type": "string"},
                                    "description": {"type": "string"},
                                    "inLanguage": {
                                        "type": "array",
                                        "items": {"type": "string"}
                                    }
                                },
                                "required": ["@context", "@type", "name", "description"]
                            }
                        },
                        "required": ["title_ar", "title_en", "description_ar", "description_en", 
                                   "tags_ar", "tags_en", "seo_keywords_ar", "seo_keywords_en",
                                   "seo_meta_description_ar", "seo_meta_description_en",
                                   "seo_title_ar", "seo_title_en", "transcript", "notes",
                                   "seo_title_suggestions", "structured_data"]
                    }
                }
            )
            
            # Clean up uploaded file
            self.client.files.delete(name=uploaded_file.name)
            
            # Parse response
            import json
            metadata = json.loads(response.text)
            
            # Validate and clean SEO metadata
            cleaned_metadata = self._validate_seo_metadata(metadata)
            
            logger.info(f"Successfully generated SEO metadata for {content_type} file")
            return True, cleaned_metadata
            
        except Exception as e:
            logger.error(f"Error generating SEO metadata: {e}")
            return False, {"error": f"AI generation failed: {str(e)}"}

    def generate_content_metadata(self, file_path: str, content_type: str) -> Tuple[bool, Dict[str, str]]:
        """
        Generate basic metadata for uploaded file using Gemini AI (Backward Compatibility)
        
        Args:
            file_path: Path to the uploaded file
            content_type: Type of content ('video', 'audio', 'pdf')
            
        Returns:
            Tuple of (success: bool, metadata: dict)
            metadata contains: title_ar, title_en, description_ar, description_en, tags
        """
        if not self.is_available():
            return False, {"error": "Gemini AI service not available"}
            
        try:
            # Upload file to Gemini
            uploaded_file = self.client.files.upload(file=file_path)
            
            # Create prompt based on content type
            prompt = self._create_prompt(content_type)
            
            # Generate content with Gemini using consistency-optimized config
            response = self.client.models.generate_content(
                model=self.model,
                contents=[prompt, uploaded_file],
                config={
                    "temperature": 0.1,  # Low temperature for deterministic outputs
                    "top_p": 0.9,       # Nucleus sampling for consistency
                    "top_k": 20,        # Limit token choices for predictability
                    "response_mime_type": "application/json",
                    "response_schema": {
                        "type": "object",
                        "properties": {
                            "title_ar": {"type": "string"},
                            "title_en": {"type": "string"},
                            "description_ar": {"type": "string"},
                            "description_en": {"type": "string"},
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"}
                            }
                        },
                        "required": ["title_ar", "title_en", "description_ar", "description_en", "tags"]
                    }
                }
            )
            
            # Clean up uploaded file
            self.client.files.delete(name=uploaded_file.name)
            
            # Parse response
            import json
            metadata = json.loads(response.text)
            
            # Validate and clean metadata
            cleaned_metadata = self._validate_metadata(metadata)
            
            logger.info(f"Successfully generated metadata for {content_type} file")
            return True, cleaned_metadata
            
        except Exception as e:
            logger.error(f"Error generating content metadata: {e}")
            return False, {"error": f"AI generation failed: {str(e)}"}
    
    def _create_prompt(self, content_type: str) -> str:
        """Create appropriate prompt based on content type"""
        
        content_type_map = {
            'video': 'فيديو (video)',
            'audio': 'تسجيل صوتي (audio recording)', 
            'pdf': 'كتاب أو وثيقة (book or document)'
        }
        
        content_desc = content_type_map.get(content_type, 'محتوى (content)')
        
        prompt = f"""
You are a senior librarian, theologian, and content analyst specialized in the
Coptic Orthodox Church of Egypt.

ALL content belongs strictly to the Coptic Orthodox Christian tradition in Egypt.

────────────────────────────────────────
ABSOLUTE SOURCE-GROUNDING RULE (MANDATORY)
────────────────────────────────────────
ALL generated metadata MUST be grounded primarily in the actual words,
phrases, and themes found in the uploaded content file.

You MUST:
- First identify key terms, repeated phrases, and explicit topics from the content.
- Use those extracted terms as the primary vocabulary source.
- Prefer wording that clearly appears in the file itself.

You MUST NOT:
- Introduce new theological concepts not explicitly present.
- Normalize the content into common church topics.
- Enrich or "improve" meaning beyond what exists in the file.

If a term or concept does not appear clearly in the content, DO NOT use it.

────────────────────────────────────────
DENOMINATIONAL CONSTRAINT (MANDATORY)
────────────────────────────────────────
Use ONLY terminology accepted by the Coptic Orthodox Church of Egypt.

You MUST:
- Use Arabic Orthodox terminology commonly used in Egypt.
- Ensure all wording is compatible with Coptic Orthodox teaching.

You MUST NOT:
- Use Protestant, Evangelical, or Catholic terminology.
- Use modern Western theological expressions.
- Introduce doctrinal interpretation.

When uncertain, choose neutral Orthodox-safe wording
directly derived from the content.

────────────────────────────────────────
GOAL
────────────────────────────────────────
Generate stable, factual, SEO-friendly metadata
for a public Coptic Orthodox digital library.

The output must be:
- Deterministic and low-variation
- Descriptive, not interpretive
- Faithful to the uploaded content

────────────────────────────────────────
CONTENT TYPE
────────────────────────────────────────
{content_desc}

────────────────────────────────────────
FIELD REQUIREMENTS
────────────────────────────────────────

1. title_ar
- Arabic only
- 3–6 words
- Constructed using key terms found in the content
- No metaphor or emotional language

2. title_en
- English
- Same meaning as Arabic title
- Based on the same extracted content terms

3. description_ar
- Arabic
- 140–160 words
- Describe:
  • subject matter
  • scope
  • intended audience
- Use vocabulary found in the content where possible
- No inferred doctrine

4. description_en
- English
- Semantically aligned with Arabic description
- Same structure and factual meaning

5. tags
- Exactly 5–6 tags
- Arabic only
- Derived from:
  • repeated keywords
  • explicit themes
  • content type
- Avoid generic church tags unless they appear in the content

────────────────────────────────────────
EXTRACTION-FIRST RULE
────────────────────────────────────────
Before composing metadata:
- Identify the most important words and phrases in the content.
- Prefer frequency and prominence over assumed importance.

Do NOT invent themes.
Do NOT generalize.

────────────────────────────────────────
THEOLOGICAL SAFETY RULE
────────────────────────────────────────
If the content does not explicitly state a belief or doctrine:
- Do NOT infer it
- Do NOT explain it
- Do NOT summarize it

Remain strictly descriptive.

────────────────────────────────────────
OUTPUT FORMAT
────────────────────────────────────────
Return ONLY valid JSON.
No explanations.
No additional text.

The JSON MUST strictly match the required schema.
"""
        
        return prompt

    def _create_complete_metadata_prompt(self, content_type: str) -> str:
        """Create comprehensive prompt for both content and SEO metadata generation"""
        
        content_type_map = {
            'video': 'فيديو (video)',
            'audio': 'تسجيل صوتي (audio recording)', 
            'pdf': 'كتاب أو وثيقة (book or document)'
        }
        
        content_desc = content_type_map.get(content_type, 'محتوى (content)')
        
        # Schema type mapping for structured data
        schema_type_map = {
            'video': 'VideoObject',
            'audio': 'AudioObject', 
            'pdf': 'Book'
        }
        
        schema_type = schema_type_map.get(content_type, 'CreativeWork')
        
        prompt = f"""
You are an expert content metadata generator specialized in
Coptic Orthodox Christian digital libraries in Egypt.

All content belongs strictly to the Coptic Orthodox Church of Egypt.

Analyze ONLY the provided text.
Do NOT assume access to the full file or external sources.

────────────────────────────────────────
CONTENT TYPE
────────────────────────────────────────
{content_desc}

────────────────────────────────────────
TASK
────────────────────────────────────────
Generate COMPLETE content and SEO metadata suitable for a
high-quality Christian digital library and search engines.

Use authentic Orthodox terminology.
Maintain theological accuracy.
Optimize for real Arabic and English search behavior.

────────────────────────────────────────
METADATA TO GENERATE
────────────────────────────────────────

Return a JSON object containing:

1. BASIC METADATA
- title_ar: Arabic title (3–6 words)
- title_en: English equivalent title
- description_ar: Arabic description (~150 words)
- description_en: English description (same meaning)
- tags: 5–6 Arabic content-based tags

2. SEO METADATA
- seo_keywords_ar: 8–12 Arabic SEO keywords
- seo_keywords_en: 8–12 English SEO keywords
- seo_meta_description_ar: Arabic meta description (~155 characters)
- seo_meta_description_en: English meta description (~155 characters)
- seo_title_suggestions:
  - ar: 3 Arabic SEO title variations
  - en: 3 English SEO title variations

3. STRUCTURED DATA
Generate minimal, valid JSON-LD using schema.org:

- @type: {schema_type}
- Language: Arabic and English
- Topic: Coptic Orthodox Church
- Publisher: Christian Library

────────────────────────────────────────
QUALITY RULES
────────────────────────────────────────
- Use clear, searchable keywords people actually use
- Mix religious and general terms naturally
- Avoid keyword stuffing
- Arabic text must be natural and RTL-friendly
- English text must be clear and readable
- Structured data must be valid and factual

────────────────────────────────────────
    OUTPUT FORMAT
    ────────────────────────────────────────
    Return ONLY valid JSON matching this structure exactly:

    {{
      "title_ar": "",
      "title_en": "",
      "description_ar": "",
      "description_en": "",
      "tags": [],
      "seo_keywords_ar": [],
      "seo_keywords_en": [],
      "seo_meta_description_ar": "",
      "seo_meta_description_en": "",
      "seo_title_suggestions": {{
        "ar": [],
        "en": []
      }},
      "structured_data": {{
        "@context": "https://schema.org",
        "@type": "{schema_type}",
        "name": "",
        "description": "",
        "inLanguage": ["ar", "en"],
        "about": {{
          "@type": "Thing",
          "name": "Coptic Orthodox Church"
        }},
        "publisher": {{
          "@type": "Organization",
          "name": "Christian Library",
          "url": "your-domain.com"
        }}
      }}
    }}

    No explanations. JSON only.
"""
        
        return prompt

    def _create_seo_prompt(self, content_type: str) -> str:
        """Create SEO-focused prompt for comprehensive metadata generation"""
        
        content_type_map = {
            'video': 'فيديو (video)',
            'audio': 'تسجيل صوتي (audio recording)', 
            'pdf': 'كتاب أو وثيقة (book or document)'
        }
        
        content_desc = content_type_map.get(content_type, 'محتوى (content)')
        
        # Schema type mapping for structured data
        schema_type_map = {
            'video': 'VideoObject',
            'audio': 'AudioObject', 
            'pdf': 'Book'
        }
        
        schema_type = schema_type_map.get(content_type, 'CreativeWork')
        
        prompt = f"""
You are a senior librarian, theologian, and SEO specialist for the Coptic Orthodox Church of Egypt's digital library.

ALL content belongs strictly to the Coptic Orthodox Christian tradition in Egypt.

────────────────────────────────────────
CONTENT EXTRACTION PRIORITY (MANDATORY)
────────────────────────────────────────
STEP 1: EXTRACT before generating
- Scan content for key phrases, repeated words, and explicit topics
- Identify specific names, places, theological terms, and concepts mentioned
- Note frequency and prominence of terms in the content

STEP 2: GROUND all metadata in extracted content
- Use actual words and phrases from the file as primary vocabulary
- Generate SEO keywords primarily from extracted terms
- Add only safe synonyms or closely related terms where appropriate

────────────────────────────────────────
SEO KEYWORD GENERATION RULES
────────────────────────────────────────
Generate exactly 30 SEO keywords per language by:

1. PRIMARY SOURCE (70% of keywords): Extract directly from content
   - Key phrases appearing in content
   - Important names and terms mentioned
   - Theological concepts explicitly stated
   - Location names and historical references

2. SAFE EXPANSION (30% of keywords): Add related terms only when:
   - They are direct translations of extracted terms
   - They are common Orthodox synonyms for extracted concepts
   - They are standard SEO variations (plurals, alternate spellings)

DO NOT:
- Invent theological concepts not in content
- Add generic church keywords unless they appear in content
- Use Protestant or non-Orthodox terminology
- Create keywords from interpretations or inferences

────────────────────────────────────────
DENOMINATIONAL CONSTRAINT (MANDATORY)
────────────────────────────────────────
Use ONLY terminology accepted by the Coptic Orthodox Church of Egypt.

MUST use Arabic Orthodox terminology common in Egypt.
MUST NOT use Protestant, Evangelical, or Catholic terms.

────────────────────────────────────────
CONTENT TYPE
────────────────────────────────────────
{content_desc}

────────────────────────────────────────
COMPREHENSIVE METADATA REQUIREMENTS
────────────────────────────────────────

1. title_ar (Arabic title, 3-6 words from content terms)
2. title_en (English equivalent, same meaning)
3. description_ar (140-160 words, content-grounded description)
4. description_en (English equivalent, same structure)

5. tags_ar (5-6 concise Arabic tags from content themes)
6. tags_en (English translations of Arabic tags)

7. seo_keywords_ar (30 Arabic SEO keywords - extracted + safe expansion)
8. seo_keywords_en (30 English SEO keywords - extracted + safe expansion)

9. seo_meta_description_ar (max 160 characters, compelling summary)
10. seo_meta_description_en (max 160 characters, English equivalent)

11. seo_title_suggestions (3 alternative English SEO titles, 50-60 chars each)

12. structured_data (JSON-LD schema.org {schema_type} markup):
    - "@context": "https://schema.org"
    - "@type": "{schema_type}"
    - "name": English title
    - "description": English description
    - "inLanguage": ["ar", "en"]
    - "author": {{"@type": "Organization", "name": "Coptic Orthodox Church"}}
    - Additional properties based on content type

────────────────────────────────────────
SEO META DESCRIPTIONS (160 chars max)
────────────────────────────────────────
Create compelling summaries that:
- Include primary keywords from content
- Are under 160 characters
- Encourage clicks while being accurate
- Use action words where appropriate

────────────────────────────────────────
SEO TITLE SUGGESTIONS
────────────────────────────────────────
Generate 3 alternative English titles (50-60 characters each):
- Include primary keywords from content
- Be unique and compelling
- Maintain theological accuracy
- Optimize for search visibility

────────────────────────────────────────
EXTRACTION-FIRST WORKFLOW
────────────────────────────────────────
1. First: Extract all key terms, phrases, and concepts from content
2. Then: Use extracted terms as foundation for all metadata
3. Finally: Add only safe, relevant expansions for SEO

Do NOT start with generic church concepts.
Do NOT normalize content into standard topics.

────────────────────────────────────────
OUTPUT FORMAT
────────────────────────────────────────
Return ONLY valid JSON matching the exact schema.
No explanations. No additional text.

ALL fields are required and must contain appropriate content.
"""
        
        return prompt
    
    def _validate_metadata(self, metadata: Dict) -> Dict[str, str]:
        """Validate and clean generated metadata"""
        
        # Default values
        defaults = {
            'title_ar': 'عنوان الملف',
            'title_en': 'File Title',
            'description_ar': 'وصف الملف',
            'description_en': 'File Description',
            'tags': []
        }
        
        # Clean and validate each field
        cleaned = {}
        
        # Titles
        cleaned['title_ar'] = str(metadata.get('title_ar', defaults['title_ar'])).strip()[:200]
        cleaned['title_en'] = str(metadata.get('title_en', defaults['title_en'])).strip()[:200]
        
        # Descriptions  
        cleaned['description_ar'] = str(metadata.get('description_ar', defaults['description_ar'])).strip()[:1000]
        cleaned['description_en'] = str(metadata.get('description_en', defaults['description_en'])).strip()[:1000]
        
        # Tags - ensure they're Arabic and clean
        tags = metadata.get('tags', [])
        if isinstance(tags, list):
            cleaned_tags = []
            for tag in tags[:6]:  # Max 6 tags to match prompt requirement
                tag_str = str(tag).strip()
                if tag_str and len(tag_str) <= 50:  # Max 50 chars per tag
                    cleaned_tags.append(tag_str)
            cleaned['tags'] = cleaned_tags
        else:
            cleaned['tags'] = []
            
        return cleaned

    def _validate_complete_metadata(self, metadata: Dict) -> Dict:
        """Validate and clean complete metadata (content + SEO)"""
        validated = {}
        
        # Basic content metadata
        validated['title_ar'] = str(metadata.get('title_ar', '')).strip()[:100]
        validated['title_en'] = str(metadata.get('title_en', '')).strip()[:100]
        validated['description_ar'] = str(metadata.get('description_ar', '')).strip()[:500]
        validated['description_en'] = str(metadata.get('description_en', '')).strip()[:500]
        
        # Tags (convert to comma-separated string for compatibility)
        tags = metadata.get('tags', [])
        if isinstance(tags, list):
            validated['tags'] = ', '.join([str(tag).strip() for tag in tags[:6] if str(tag).strip()])
        else:
            validated['tags'] = str(tags).strip()[:200]
        
        # SEO Keywords
        seo_keywords_ar = metadata.get('seo_keywords_ar', [])
        if isinstance(seo_keywords_ar, list):
            validated['seo_keywords_ar'] = ', '.join([str(kw).strip() for kw in seo_keywords_ar[:12] if str(kw).strip()])
        else:
            validated['seo_keywords_ar'] = str(seo_keywords_ar).strip()[:300]
            
        seo_keywords_en = metadata.get('seo_keywords_en', [])
        if isinstance(seo_keywords_en, list):
            validated['seo_keywords_en'] = ', '.join([str(kw).strip() for kw in seo_keywords_en[:12] if str(kw).strip()])
        else:
            validated['seo_keywords_en'] = str(seo_keywords_en).strip()[:300]
        
        # SEO Meta Descriptions
        validated['seo_meta_description_ar'] = str(metadata.get('seo_meta_description_ar', '')).strip()[:160]
        validated['seo_meta_description_en'] = str(metadata.get('seo_meta_description_en', '')).strip()[:160]
        
        # SEO Title Suggestions
        seo_titles = metadata.get('seo_title_suggestions', {})
        if isinstance(seo_titles, dict):
            import json
            validated['seo_title_suggestions'] = json.dumps(seo_titles, ensure_ascii=False)
        else:
            validated['seo_title_suggestions'] = '{}'
        
        # Structured Data
        structured_data = metadata.get('structured_data', {})
        if isinstance(structured_data, dict):
            validated['structured_data'] = structured_data
        else:
            validated['structured_data'] = {}
        
        return validated

    def _validate_seo_metadata(self, metadata: Dict) -> Dict:
        """Validate and clean generated SEO metadata"""
        import json
        
        # Default values
        defaults = {
            'title_ar': 'عنوان الملف',
            'title_en': 'File Title',
            'description_ar': 'وصف الملف',
            'description_en': 'File Description',
            'tags_ar': [],
            'tags_en': [],
            'seo_keywords_ar': [],
            'seo_keywords_en': [],
            'seo_meta_description_ar': 'وصف قصير للمحتوى',
            'seo_meta_description_en': 'Short content description',
            'seo_title_suggestions': [],
            'structured_data': {}
        }
        
        # Clean and validate each field
        cleaned = {}
        
        # Basic titles and descriptions
        cleaned['title_ar'] = str(metadata.get('title_ar', defaults['title_ar'])).strip()[:200]
        cleaned['title_en'] = str(metadata.get('title_en', defaults['title_en'])).strip()[:200]
        cleaned['description_ar'] = str(metadata.get('description_ar', defaults['description_ar'])).strip()[:1000]
        cleaned['description_en'] = str(metadata.get('description_en', defaults['description_en'])).strip()[:1000]
        
        # Tags (max 6 each language)
        cleaned['tags_ar'] = self._validate_string_array(
            metadata.get('tags_ar', []), max_items=6, max_length=50
        )
        cleaned['tags_en'] = self._validate_string_array(
            metadata.get('tags_en', []), max_items=6, max_length=50
        )
        
        # SEO Keywords (max 30 each language)
        cleaned['seo_keywords_ar'] = self._validate_string_array(
            metadata.get('seo_keywords_ar', []), max_items=30, max_length=100
        )
        cleaned['seo_keywords_en'] = self._validate_string_array(
            metadata.get('seo_keywords_en', []), max_items=30, max_length=100
        )
        
        # SEO Meta Descriptions (max 160 chars each)
        cleaned['seo_meta_description_ar'] = str(
            metadata.get('seo_meta_description_ar', defaults['seo_meta_description_ar'])
        ).strip()[:160]
        cleaned['seo_meta_description_en'] = str(
            metadata.get('seo_meta_description_en', defaults['seo_meta_description_en'])
        ).strip()[:160]
        
        # SEO Title Suggestions (max 3, max 60 chars each)
        cleaned['seo_title_suggestions'] = self._validate_string_array(
            metadata.get('seo_title_suggestions', []), max_items=3, max_length=60
        )
        
        # Structured Data - validate as proper JSON object
        structured_data = metadata.get('structured_data', {})
        if isinstance(structured_data, dict):
            # Ensure required schema.org fields
            if '@context' not in structured_data:
                structured_data['@context'] = 'https://schema.org'
            if '@type' not in structured_data:
                structured_data['@type'] = 'CreativeWork'
            if 'name' not in structured_data:
                structured_data['name'] = cleaned['title_en']
            if 'description' not in structured_data:
                structured_data['description'] = cleaned['description_en']
            
            cleaned['structured_data'] = structured_data
        else:
            # Default structured data if invalid
            cleaned['structured_data'] = {
                '@context': 'https://schema.org',
                '@type': 'CreativeWork',
                'name': cleaned['title_en'],
                'description': cleaned['description_en'],
                'inLanguage': ['ar', 'en'],
                'author': {
                    '@type': 'Organization',
                    'name': 'Coptic Orthodox Church'
                }
            }
            
        return cleaned
    
    def _validate_string_array(self, arr, max_items: int, max_length: int) -> list:
        """Helper to validate and clean array of strings"""
        if not isinstance(arr, list):
            return []
        
        cleaned_items = []
        for item in arr[:max_items]:
            item_str = str(item).strip()
            if item_str and len(item_str) <= max_length:
                cleaned_items.append(item_str)
        
        return cleaned_items


# Singleton instance
_gemini_service = None

def get_gemini_service() -> GeminiContentGenerator:
    """Get singleton instance of Gemini service"""
    global _gemini_service
    if _gemini_service is None:
        _gemini_service = GeminiContentGenerator()
    return _gemini_service