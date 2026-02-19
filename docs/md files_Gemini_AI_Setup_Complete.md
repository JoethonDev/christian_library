# Gemini AI Setup Checklist & Requirements

## ✅ **Implementation Status: COMPLETE**

All core components have been implemented and tested. The system is production-ready for **Coptic Orthodox Christian content** with enhanced denominational safety and source-grounding rules.

---

## 🚀 **Quick Setup Guide**

### 1. **Environment Variables (REQUIRED)**
Set these environment variables on your system:

```bash
# Required - Get from Google AI Studio
export GEMINI_API_KEY="your-actual-api-key-here"

# Optional - Defaults to optimal model
export GEMINI_MODEL="gemini-2.5-flash"
```

**Windows users:**
```cmd
set GEMINI_API_KEY=your-actual-api-key-here
set GEMINI_MODEL=gemini-2.5-flash
```

### 2. **Get Your API Key**
1. Visit [Google AI Studio](https://aistudio.google.com/apikey)
2. Sign in with your Google account
3. Click "Create API Key"
4. Copy the generated key
5. Set it as `GEMINI_API_KEY` environment variable

### 3. **Test the Setup**
```bash
cd library_prod
python test_gemini_integration.py
```

Expected output:
```
✅ Django setup successful
✅ Gemini service import successful
✅ Service initialized, available: True
🎉 Gemini AI integration is ready!
```

### 4. **Start the Server**
```bash
cd library_prod/backend
python manage.py runserver
```

### 5. **Test AI Generation**
1. Navigate to `http://localhost:8000/admin/upload/`
2. Select content type (Video, Audio, or Document)
3. Choose a file
4. Click **"Generate with AI"** ✨
5. Verify form fields are populated

---

## 🔧 **What's Implemented**

### ✅ **Backend Components**
- **Gemini Service**: [`media_manager/services/gemini_service.py`](backend/apps/media_manager/services/gemini_service.py)
- **Admin Endpoint**: `/admin/upload/generate/` for AI processing
- **Django Settings**: `GEMINI_API_KEY` and `GEMINI_MODEL` configuration
- **URL Routing**: Proper endpoint mapping
- **Dependencies**: `google-genai>=0.8.0` and `pdfminer.six>=20231228`

### ✅ **Frontend Components**
- **AI Button**: Purple gradient "Generate with AI" button with sparkles icon
- **JavaScript**: AJAX handling, form population, loading states
- **Error Handling**: User-friendly error messages and alerts
- **Loading States**: Visual feedback during AI processing

### ✅ **Model Configuration**
- **Default Model**: `gemini-2.5-flash` (optimal for this use case)
- **Configurable**: Override via `GEMINI_MODEL` environment variable
- **Enhanced Config**: Low temperature (0.1), nucleus sampling (top_p=0.9), limited tokens (top_k=20)
- **Consistency**: Deterministic outputs for stable, repeatable results
- **Coptic Orthodox Safe**: Denominational constraints built into prompting

---

## ⚙️ **Model Selection Rationale**

**Default: `gemini-2.5-flash`** - Chosen because it offers:

| Feature | Benefit |
|---------|---------|
| **Price-Performance** | Best balance for production use |
| **Large-Scale Processing** | Handles multiple files efficiently |
| **Low Latency** | Fast response times for better UX |
| **Multilingual Support** | Excellent Arabic/English accuracy |
| **Content Analysis** | Superior at summarizing media content |
| **Stability** | Production-ready, not experimental |

**Alternative Models** (configurable via `GEMINI_MODEL`):
- `gemini-2.5-pro` - Higher accuracy, slower response
- `gemini-3-flash` - Latest model, may have rate limits
- `gemini-2.0-flash` - Previous generation, stable

---

## 🎯 **Enhanced Coptic Orthodox Prompt**

### **Specialized Implementation** ✅
The prompt has been **completely rewritten** for Coptic Orthodox content with these critical features:

**Denominational Constraints:**
- ✅ **Coptic Orthodox Only**: Uses only terminology accepted by the Coptic Orthodox Church of Egypt
- ✅ **No Western Terms**: Prohibits Protestant, Evangelical, or Catholic terminology
- ✅ **Orthodox-Safe Wording**: Ensures compatibility with Coptic Orthodox teaching

**Source-Grounding Rules:**
- ✅ **Content Extraction**: Uses only words, phrases, and themes found in uploaded files
- ✅ **No Inference**: Prohibits adding theological concepts not explicitly present
- ✅ **No Normalization**: Avoids "improving" content beyond what exists
- ✅ **Frequency-Based**: Prefers prominent terms from actual content

**Enhanced Consistency:**
- ✅ **Low Temperature**: 0.1 for deterministic outputs
- ✅ **Nucleus Sampling**: top_p=0.9 for stable generation
- ✅ **Limited Tokens**: top_k=20 for predictable results
- ✅ **Theological Safety**: Remains strictly descriptive, no interpretation

---

## ❌ **What's Missing / Setup Requirements**

### **REQUIRED for Functionality:**
1. **API Key**: Must set `GEMINI_API_KEY` environment variable
2. **Internet Connection**: Required for Gemini API calls
3. **File Upload**: Admin users need proper Django authentication

### **OPTIONAL Enhancements:**
1. **Monitoring**: Add logging for API usage and costs
2. **Rate Limiting**: Implement client-side rate limiting for heavy usage
3. **Caching**: Cache results for identical files
4. **Batch Processing**: Generate metadata for multiple files at once
5. **Quality Feedback**: Allow users to rate AI-generated content

### **Production Considerations:**
1. **API Quotas**: Monitor Gemini API usage limits
2. **Error Alerting**: Set up monitoring for AI generation failures
3. **Content Validation**: Review AI-generated content quality
4. **Cost Management**: Track API usage costs

---

## 🧪 **Testing Scenarios**

### **Test Case 1: Successful Generation**
1. Upload a clear Arabic sermon video
2. Expected: Arabic title, English translation, relevant tags
3. Verify: Content is factual and SEO-optimized

### **Test Case 2: Error Handling**
1. Try without API key set
2. Expected: "AI service not available" error
3. Verify: User-friendly error message, button re-enabled

### **Test Case 3: File Type Validation**
1. Upload wrong file type for selected content type
2. Expected: Validation error before AI processing
3. Verify: Clear error message about file type mismatch

### **Test Case 4: Large File Processing**
1. Upload large video/audio file (>100MB)
2. Expected: Successful processing (may take longer)
3. Verify: Loading state shows during processing

---

## 📊 **Performance Expectations**

| Content Type | Expected Response Time | File Size Limit |
|-------------|----------------------|----------------|
| **PDF** | 2-5 seconds | Up to 50MB |
| **Audio** | 5-15 seconds | Up to 100MB |
| **Video** | 10-30 seconds | Up to 500MB |

**Note**: Response times depend on file size and Gemini API load.

---

## 🚨 **Troubleshooting**

### **Common Issues:**

**"Service not available"**
- ✅ Check `GEMINI_API_KEY` is set correctly
- ✅ Verify API key is valid at [AI Studio](https://aistudio.google.com/)
- ✅ Confirm internet connectivity

**"Generation failed"**
- ✅ Check file size isn't too large
- ✅ Verify file format is supported
- ✅ Try with a different file

**"Network error"**
- ✅ Check internet connection
- ✅ Verify Gemini API status
- ✅ Check firewall/proxy settings

**Button doesn't work**
- ✅ Select content type first
- ✅ Choose a file before clicking Generate
- ✅ Check browser console for JavaScript errors

---

## ✨ **Ready for Production!**

The Gemini AI integration is **complete and production-ready**. Simply set your API key and start generating high-quality, SEO-optimized metadata for your Christian library content!

**Next Steps:**
1. Set `GEMINI_API_KEY` environment variable
2. Test with sample files
3. Train admin users on the new feature
4. Monitor API usage and costs
5. Collect feedback for future improvements