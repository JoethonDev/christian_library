"""
PostgreSQL optimization migration for Arabic text search performance.

This migration creates optimized indexes and configurations for high-performance
Arabic text search with trigram matching and GIN indexes.
"""

from django.db import migrations, connection
from django.contrib.postgres.operations import TrigramExtension


def create_arabic_search_indexes(apps, schema_editor):
    """
    Create optimized indexes for Arabic text search performance.
    """
    if 'postgresql' not in connection.settings_dict['ENGINE']:
        return  # Skip if not using PostgreSQL
    
    with connection.cursor() as cursor:
        # Enable required extensions
        cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        cursor.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")
        
        # Create trigram indexes for fuzzy Arabic text matching
        indexes = [
            # Primary content search indexes
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contentitem_title_ar_trgm 
            ON media_manager_contentitem 
            USING gin (title_ar gin_trgm_ops);
            """,
            
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contentitem_description_ar_trgm 
            ON media_manager_contentitem 
            USING gin (description_ar gin_trgm_ops);
            """,
            
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contentitem_book_content_trgm 
            ON media_manager_contentitem 
            USING gin (book_content gin_trgm_ops);
            """,
            
            # Optimized search vector index with Arabic configuration
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contentitem_search_vector_arabic
            ON media_manager_contentitem 
            USING gin (search_vector);
            """,
            
            # Composite index for content type + active status + search
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contentitem_active_type_search
            ON media_manager_contentitem (content_type, is_active) 
            WHERE is_active = true;
            """,
            
            # Specialized PDF content index
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contentitem_pdf_content_length
            ON media_manager_contentitem (content_type, char_length(book_content))
            WHERE content_type = 'pdf' AND book_content IS NOT NULL;
            """,
        ]
        
        for index_sql in indexes:
            try:
                cursor.execute(index_sql)
            except Exception as e:
                print(f"Warning: Could not create index: {e}")


def create_arabic_search_functions(apps, schema_editor):
    """
    Create custom PostgreSQL functions for enhanced Arabic search.
    """
    if 'postgresql' not in connection.settings_dict['ENGINE']:
        return
    
    with connection.cursor() as cursor:
        # Function to normalize Arabic text for search
        arabic_normalize_function = """
        CREATE OR REPLACE FUNCTION arabic_normalize(text) 
        RETURNS text AS $$
        BEGIN
            RETURN regexp_replace(
                regexp_replace(
                    regexp_replace(
                        regexp_replace($1, '[أإآء]', 'ا', 'g'),
                        'ة', 'ه', 'g'
                    ),
                    'ى', 'ي', 'g'
                ),
                '[ًٌٍَُِّْ]', '', 'g'  -- Remove diacritics
            );
        END;
        $$ LANGUAGE plpgsql IMMUTABLE;
        """
        
        # Function for Arabic similarity search
        arabic_similarity_function = """
        CREATE OR REPLACE FUNCTION arabic_similarity(text, text) 
        RETURNS float AS $$
        BEGIN
            RETURN similarity(arabic_normalize($1), arabic_normalize($2));
        END;
        $$ LANGUAGE plpgsql IMMUTABLE;
        """
        
        # Function for Arabic content search ranking
        arabic_search_rank_function = """
        CREATE OR REPLACE FUNCTION arabic_search_rank(
            search_vector tsvector, 
            query tsquery, 
            content_length integer DEFAULT 1000
        ) RETURNS float AS $$
        BEGIN
            -- Custom ranking that considers Arabic text characteristics
            RETURN ts_rank_cd(
                search_vector, 
                query, 
                1 | 2 | 4 | 8  -- Use all ranking methods
            ) * (1.0 + (1000.0 / GREATEST(content_length, 1)));  -- Boost shorter, relevant content
        END;
        $$ LANGUAGE plpgsql IMMUTABLE;
        """
        
        functions = [
            arabic_normalize_function,
            arabic_similarity_function, 
            arabic_search_rank_function
        ]
        
        for function_sql in functions:
            try:
                cursor.execute(function_sql)
            except Exception as e:
                print(f"Warning: Could not create function: {e}")


def optimize_arabic_search_config(apps, schema_editor):
    """
    Optimize PostgreSQL configuration for Arabic text search.
    """
    if 'postgresql' not in connection.settings_dict['ENGINE']:
        return
    
    with connection.cursor() as cursor:
        # Create Arabic text search configuration if it doesn't exist
        try:
            cursor.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_ts_config WHERE cfgname = 'arabic_optimized'
                    ) THEN
                        CREATE TEXT SEARCH CONFIGURATION arabic_optimized ( COPY = arabic );
                        
                        -- Optimize for Arabic content
                        ALTER TEXT SEARCH CONFIGURATION arabic_optimized
                        ALTER MAPPING FOR asciiword, asciihword, hword_asciipart, word, hword, hword_part
                        WITH simple;
                    END IF;
                END$$;
            """)
        except Exception as e:
            print(f"Warning: Could not create Arabic search configuration: {e}")


def remove_arabic_search_indexes(apps, schema_editor):
    """
    Remove Arabic search indexes (reverse migration).
    """
    if 'postgresql' not in connection.settings_dict['ENGINE']:
        return
    
    with connection.cursor() as cursor:
        indexes_to_drop = [
            'idx_contentitem_title_ar_trgm',
            'idx_contentitem_description_ar_trgm', 
            'idx_contentitem_book_content_trgm',
            'idx_contentitem_search_vector_arabic',
            'idx_contentitem_active_type_search',
            'idx_contentitem_pdf_content_length'
        ]
        
        for index_name in indexes_to_drop:
            try:
                cursor.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {index_name};")
            except Exception as e:
                print(f"Warning: Could not drop index {index_name}: {e}")


def remove_arabic_search_functions(apps, schema_editor):
    """
    Remove custom Arabic search functions (reverse migration).
    """
    if 'postgresql' not in connection.settings_dict['ENGINE']:
        return
    
    with connection.cursor() as cursor:
        functions_to_drop = [
            'arabic_normalize(text)',
            'arabic_similarity(text, text)',
            'arabic_search_rank(tsvector, tsquery, integer)'
        ]
        
        for function_name in functions_to_drop:
            try:
                cursor.execute(f"DROP FUNCTION IF EXISTS {function_name};")
            except Exception as e:
                print(f"Warning: Could not drop function {function_name}: {e}")


class Migration(migrations.Migration):
    atomic = False
    
    dependencies = [
        ('media_manager', '0001_initial'),  # Adjust to your last migration
    ]
    
    operations = [
        # Enable trigram extension
        TrigramExtension(),
        
        # Create Arabic search indexes
        migrations.RunPython(
            create_arabic_search_indexes,
            remove_arabic_search_indexes,
            atomic=False  # Required for CONCURRENTLY operations
        ),
        
        # Create Arabic search functions
        migrations.RunPython(
            create_arabic_search_functions,
            remove_arabic_search_functions
        ),
        
        # Optimize Arabic search configuration
        migrations.RunPython(
            optimize_arabic_search_config,
            migrations.RunPython.noop
        ),
    ]