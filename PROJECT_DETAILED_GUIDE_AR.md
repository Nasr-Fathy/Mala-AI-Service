<div dir="rtl">
# دليل المشروع التفصيلي -- خدمة الذكاء الاصطناعي المالية

**الإصدار:** 1.0.0
**آخر تحديث:** أبريل 2026

---

## جدول المحتويات

1. [نظرة عامة على المشروع](#1-نظرة-عامة-على-المشروع)
2. [شرح الهندسة المعمارية](#2-شرح-الهندسة-المعمارية)
3. [شرح المجلدات والملفات](#3-شرح-المجلدات-والملفات)
4. [شرح الكود بالتفصيل](#4-شرح-الكود-بالتفصيل)
5. [شرح المكتبات المستخدمة](#5-شرح-المكتبات-المستخدمة)
6. [الأنماط والمفاهيم المستخدمة](#6-الأنماط-والمفاهيم-المستخدمة)
7. [شرح الاختبارات](#7-شرح-الاختبارات)
8. [تدفق النظام من البداية للنهاية](#8-تدفق-النظام-من-البداية-للنهاية)
9. [كيفية تشغيل المشروع](#9-كيفية-تشغيل-المشروع)
10. [كيفية اختبار المشروع](#10-كيفية-اختبار-المشروع)
11. [شرح معمق للأنماط الرئيسية](#11-شرح-معمق-للأنماط-الرئيسية)

---

## 1. نظرة عامة على المشروع

### ما هو هذا المشروع؟

هذا المشروع هو **خدمة مصغرة** (Microservice) مبنية بإطار عمل FastAPI، مهمتها معالجة المستندات المالية (ملفات PDF) باستخدام الذكاء الاصطناعي.

تخيل أن لديك تقريراً مالياً لشركة ما -- قوائم مالية مكتوبة بالعربية والإنجليزية في ملف PDF. هذه الخدمة تأخذ ذلك الملف وتقوم بـ:

1. **استخراج النصوص والجداول** (OCR) -- ترسل الملف إلى نموذج ذكاء اصطناعي (Google Gemini) الذي "يقرأ" الصفحات ويحولها إلى بيانات منظمة (JSON).
2. **التحليل المالي المتعدد المراحل** (Financial Mapping) -- تمرر البيانات المستخرجة عبر 4 مراحل من الذكاء الاصطناعي لاستخلاص: بيانات الشركة، الفترات المالية، بنود القوائم المالية، والملاحظات.

### ما المشكلة التي يحلها؟

في الأصل، كانت هذه العمليات مدمجة داخل مشروع Django كبير (يسمى Backend أو الخادم الرئيسي). المشكلة أن:

- **عمليات الذكاء الاصطناعي بطيئة** -- استدعاء نموذج LLM يستغرق 10-60 ثانية. إذا كانت مدمجة في Django، فإنها تحتل موارد الخادم الرئيسي.
- **التوسع صعب** -- لا يمكنك توسيع قدرة معالجة الذكاء الاصطناعي بشكل مستقل عن بقية التطبيق.
- **الصيانة معقدة** -- خلط كود الذكاء الاصطناعي مع كود إدارة المستخدمين والأعمال يجعل الصيانة صعبة.

الحل هو **فصل عمليات الذكاء الاصطناعي** في خدمة مستقلة. Django يرسل الملف عبر HTTP، الخدمة تعالجه وترجع النتيجة، Django يحفظ النتيجة في قاعدة البيانات.

### الهندسة على مستوى عالٍ

```
Django Backend (Celery Worker)
        |
        | HTTP POST (ملف PDF أو بيانات JSON)
        v
+----------------------------+
|  خدمة الذكاء الاصطناعي     |
|     (FastAPI)              |
+----------------------------+
        |
        | Vertex AI SDK (gRPC)
        v
+----------------------------+
|   Google Vertex AI         |
|   Gemini 1.5 Pro           |
+----------------------------+
```

**الخدمة لا تحتوي على قاعدة بيانات.** هي خدمة بدون حالة (Stateless) -- تستقبل طلباً، تعالجه، وترجع النتيجة. الحالة (Pipeline state) تبقى في Django.

---

## 2. شرح الهندسة المعمارية

### ما هو نمط الهندسة المستخدم؟

المشروع يتبع مزيجاً من:

1. **العمارة الطبقية** (Layered Architecture) -- الكود مقسم إلى طبقات واضحة: API، Services، Pipeline، Core.
2. **العمارة النظيفة** (Clean Architecture) -- كل طبقة لديها مسؤولية واحدة ولا تعرف تفاصيل الطبقات الأخرى.
3. **نمط الخدمة المصغرة** (Microservice Pattern) -- الخدمة مستقلة تماماً عن Django، تتواصل عبر HTTP فقط.

### لماذا هذه الهندسة؟

**البديل الأول: كل شيء في ملف واحد**
يمكنك وضع كل الكود في ملف `main.py` واحد. هذا يعمل لمشروع صغير، لكن عندما يكبر المشروع:
- لا يمكنك اختبار جزء بمعزل عن الباقي.
- تغيير نموذج الذكاء الاصطناعي يتطلب تعديل عشرات الأماكن.
- مطوران لا يمكنهما العمل على الملف نفسه بسهولة.

**البديل الثاني: العمارة الطبقية البسيطة**
تقسيم الكود إلى طبقات (API, Service, Data) بدون تجريد (Abstraction). هذا أفضل، لكن:
- إذا أردت تغيير Gemini إلى GPT-4، ستحتاج لتعديل كل ملف يستدعي Gemini.
- لا يوجد فصل بين "ما نريد فعله" (Interface) و"كيف نفعله" (Implementation).

**ما نستخدمه: عمارة نظيفة مع تجريد**
- واجهة مجردة (Abstract Interface) لنموذج الذكاء الاصطناعي: `BaseLLMClient`
- تطبيق محدد (Concrete Implementation): `VertexLLMClient`
- مصنع (Factory) لاختيار التطبيق: `create_llm_client()`
- الخدمات تعتمد على الواجهة المجردة، ليس على التطبيق المحدد.

هذا يعني: تغيير نموذج الذكاء الاصطناعي = كتابة class جديد + تغيير متغير بيئة واحد. لا تغيير في أي service أو endpoint.

### الطبقات الخمس

```
app/
├── core/        ← الإعدادات، التسجيل (Logging)، الأخطاء
├── api/         ← نقاط النهاية (Endpoints)، حقن التبعيات
├── services/    ← منطق الأعمال (LLM، PDF، OCR، Mapping)
├── pipeline/    ← إطار التنظيم (Orchestration framework)
├── validation/  ← التحقق من مخرجات الذكاء الاصطناعي
└── middleware/  ← طبقة وسيطة (Request ID)
```

**طبقة Core** -- الأساسيات التي يعتمد عليها كل شيء آخر: الإعدادات من ملف `.env`، تهيئة نظام التسجيل (Logging)، وهرمية الأخطاء (Exception hierarchy).

**طبقة API** -- تستقبل طلبات HTTP وتعيد استجابات JSON. لا تحتوي على أي منطق أعمال -- فقط تستدعي الخدمات وتعيد النتيجة.

**طبقة Services** -- تحتوي على المنطق الفعلي: كيف نتواصل مع Gemini، كيف نعالج PDF، كيف ننفذ OCR، كيف نشغّل الـ 4 مراحل.

**طبقة Pipeline** -- إطار عمل عام لتنظيم خطوات متتابعة. كل خطوة (Step) هي class مستقل يمكن اختباره وتبديله.

**طبقة Validation** -- تتحقق أن مخرجات نموذج الذكاء الاصطناعي تطابق المخطط المتوقع (JSON Schema) قبل إعادتها.

**طبقة Middleware** -- طبقة وسيطة تعمل قبل وبعد كل طلب. حالياً تولّد معرّف فريد (Request ID) لكل طلب لتسهيل تتبع السجلات.

---

## 3. شرح المجلدات والملفات

### هيكل المشروع الكامل

```
ai-service/
├── app/
│   ├── __init__.py
│   ├── main.py                          ← نقطة البداية: إنشاء التطبيق
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py                    ← إعدادات التطبيق من متغيرات البيئة
│   │   ├── logging.py                   ← تهيئة نظام التسجيل المنظم
│   │   └── exceptions.py               ← هرمية الأخطاء المخصصة
│   ├── middleware/
│   │   ├── __init__.py
│   │   └── request_id.py               ← توليد معرّف فريد لكل طلب
│   ├── api/
│   │   ├── __init__.py
│   │   ├── deps.py                      ← حقن التبعيات (Dependency Injection)
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── router.py               ← تجميع كل المسارات
│   │       └── endpoints/
│   │           ├── __init__.py
│   │           ├── health.py            ← فحص الصحة
│   │           ├── capture.py           ← رفع PDF واستخراج OCR
│   │           ├── mapping.py           ← التحليل المالي
│   │           └── pipeline.py          ← التنفيذ الكامل
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── common.py                    ← نماذج مشتركة (HealthResponse, etc.)
│   │   ├── capture.py                   ← نماذج استجابة OCR
│   │   ├── mapping.py                   ← نماذج طلب/استجابة Mapping
│   │   └── pipeline.py                  ← نماذج طلب/استجابة Pipeline
│   ├── services/
│   │   ├── __init__.py
│   │   ├── llm/
│   │   │   ├── __init__.py
│   │   │   ├── base.py                  ← الواجهة المجردة لنموذج الذكاء الاصطناعي
│   │   │   ├── vertex.py                ← تطبيق Vertex AI (Gemini)
│   │   │   └── factory.py               ← مصنع لإنشاء العميل المناسب
│   │   ├── pdf/
│   │   │   ├── __init__.py
│   │   │   └── layout_service.py        ← معالجة PDF باستخدام PyMuPDF
│   │   ├── capture/
│   │   │   ├── __init__.py
│   │   │   └── capture_service.py       ← تنسيق عملية OCR
│   │   └── mapping/
│   │       ├── __init__.py
│   │       ├── base_mapper.py           ← إطار الـ 4 مراحل المجرد
│   │       ├── financial_mapper.py      ← التطبيق المالي الفعلي
│   │       ├── category_mapper.py       ← تصنيف البنود بالكلمات المفتاحية
│   │       └── prompts/
│   │           ├── __init__.py          ← تصدير الـ Prompts
│   │           ├── metadata.py          ← Prompt المرحلة الأولى
│   │           ├── period.py            ← Prompt المرحلة الثانية
│   │           ├── statement.py         ← Prompt المرحلة الثالثة
│   │           └── notes.py             ← Prompt المرحلة الرابعة
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── base_step.py                 ← واجهة خطوة الخط الإنتاجي
│   │   ├── registry.py                  ← سجل الخطوات
│   │   ├── orchestrator.py              ← المنظم (ينفذ الخطوات بالتتابع)
│   │   └── steps/
│   │       ├── __init__.py
│   │       ├── capture_step.py          ← يغلّف CaptureService كخطوة
│   │       └── mapping_step.py          ← يغلّف FinancialMapperService كخطوة
│   └── validation/
│       ├── __init__.py
│       ├── schema_validator.py          ← تحميل وتشغيل JSON Schema
│       └── schemas/
│           ├── capture_output.json      ← مخطط مخرجات OCR
│           └── financial/
│               ├── metadata_schema.json
│               ├── period_schema.json
│               ├── statement_schema.json
│               └── notes_schema.json
├── tests/
│   ├── __init__.py
│   ├── conftest.py                      ← إعداد الاختبارات والـ Fixtures
│   ├── test_api.py                      ← اختبار نقاط النهاية
│   ├── test_capture.py                  ← اختبار خدمة OCR
│   ├── test_mapping.py                  ← اختبار خدمة Mapping
│   └── test_pipeline.py                 ← اختبار المنظم والخطوات
├── Dockerfile                           ← بناء صورة Docker
├── docker-compose.yml                   ← تشغيل الخدمة
├── requirements.txt                     ← المكتبات المطلوبة
├── .env.example                         ← مثال متغيرات البيئة
└── pytest.ini                           ← إعدادات pytest
```

### شرح كل مجلد

#### `app/core/` -- القلب

هذا المجلد يحتوي على الأساسيات التي لا تتغير كثيراً:

- **`config.py`** -- يقرأ كل الإعدادات من متغيرات البيئة (Environment Variables). بدلاً من كتابة القيم مباشرة في الكود (وهو خطأ أمني)، نضعها في ملف `.env` والكود يقرأها تلقائياً.

- **`logging.py`** -- يهيئ نظام التسجيل. في التطوير، السجلات تظهر ملونة في الطرفية. في الإنتاج، تظهر كـ JSON منظم يمكن لأدوات مثل CloudWatch أو ELK تحليله.

- **`exceptions.py`** -- يعرّف أنواع الأخطاء. بدلاً من أن يُرجع كل خطأ رسالة "حدث خطأ"، كل نوع خطأ لديه رمز فريد (مثل `LLM_ERROR`، `PDF_ERROR`) ورمز HTTP مناسب (422 لأخطاء المدخلات، 500 للأخطاء الداخلية).

#### `app/middleware/` -- الطبقة الوسيطة

- **`request_id.py`** -- كل طلب HTTP يدخل الخدمة يحصل على معرّف فريد (UUID). هذا المعرّف يُضاف تلقائياً لكل سجل (Log) يُكتب أثناء معالجة الطلب. بدون هذا، إذا وصل 10 طلبات في نفس الوقت، لن تستطيع التمييز بين سجلات كل طلب.

#### `app/api/` -- واجهة التطبيق

- **`deps.py`** -- دوال مساعدة تسترجع الكائنات (Objects) المخزنة في `app.state`. FastAPI يستدعي هذه الدوال تلقائياً عندما يحتاج endpoint لخدمة معينة. هذا يسمى **حقن التبعيات** (Dependency Injection).

- **`v1/router.py`** -- يجمع كل المسارات (Routes) من ملفات الـ endpoints في router واحد. الـ `v1` يعني أن هذا الإصدار الأول من الـ API. إذا غيرنا الـ API مستقبلاً، ننشئ `v2/` بدون كسر التوافق.

- **`v1/endpoints/`** -- كل ملف يمثل مجموعة من نقاط النهاية:
  - `health.py` -- فحص صحة الخدمة (هل تعمل؟) وجاهزيتها (هل Gemini يستجيب؟)
  - `capture.py` -- رفع ملف PDF وتشغيل OCR
  - `mapping.py` -- إرسال بيانات OCR وتشغيل التحليل المالي
  - `pipeline.py` -- رفع PDF وتشغيل كل شيء (OCR + Mapping) في طلب واحد

#### `app/schemas/` -- نماذج البيانات

هذه نماذج Pydantic تعرّف شكل البيانات الداخلة والخارجة من الـ API. مثلاً:
- `CaptureResponse` يحدد أن استجابة OCR يجب أن تحتوي على `raw_text` (نص)، `pages` (قائمة صفحات)، `tables` (قائمة جداول)، إلخ.
- إذا حاولت إرجاع بيانات لا تطابق النموذج، FastAPI يرفض ويرجع خطأ.

#### `app/services/` -- المنطق الفعلي

هنا يعيش "الذكاء":

- **`llm/`** -- كل ما يتعلق بالتواصل مع نموذج الذكاء الاصطناعي:
  - `base.py` -- واجهة مجردة تقول "أي عميل LLM يجب أن يوفر هذه الدوال"
  - `vertex.py` -- التطبيق الفعلي الذي يتواصل مع Google Gemini
  - `factory.py` -- ينظر في الإعدادات ويقرر أي تطبيق يُنشئ

- **`pdf/`** -- `LayoutService` يتعامل مع ملفات PDF في الذاكرة (بدون حفظ على القرص): عد الصفحات، استخراج صفحات محددة.

- **`capture/`** -- `CaptureService` ينسّق عملية OCR: يستخرج الصفحات، يرسلها لـ Gemini، يتحقق من النتيجة، يُرجع البيانات المنظمة.

- **`mapping/`** -- النظام المتعدد المراحل:
  - `base_mapper.py` -- إطار مجرد يعرّف كيف تعمل الـ 4 مراحل
  - `financial_mapper.py` -- التطبيق الفعلي للقوائم المالية
  - `category_mapper.py` -- تصنيف بنود القوائم المالية باستخدام كلمات مفتاحية
  - `prompts/` -- النصوص التوجيهية (Prompts) التي تُرسل لنموذج الذكاء الاصطناعي

#### `app/pipeline/` -- إطار التنظيم

- **`base_step.py`** -- واجهة تقول "أي خطوة في الخط الإنتاجي يجب أن توفر `execute()` و`validate_input()`"
- **`registry.py`** -- سجل يحتفظ بالخطوات المسجلة بترتيب التسجيل
- **`orchestrator.py`** -- المنظم الذي يمشي على الخطوات واحدة تلو الأخرى، يتحقق من المدخلات، ينفذ، ويتوقف عند أول فشل
- **`steps/`** -- خطوات فعلية تغلّف الخدمات:
  - `capture_step.py` يغلّف `CaptureService`
  - `mapping_step.py` يغلّف `FinancialMapperService`

#### `app/validation/` -- التحقق

- **`schema_validator.py`** -- يحمّل ملفات JSON Schema من القرص ويتحقق أن بيانات مخرجات الذكاء الاصطناعي تطابقها.
- **`schemas/`** -- ملفات JSON Schema الفعلية. كل ملف يعرّف الحقول المطلوبة وأنواعها لكل مرحلة.

#### `tests/` -- الاختبارات

- **`conftest.py`** -- إعداد مشترك لكل الاختبارات: عميل LLM وهمي، بيانات اختبار، عميل HTTP وهمي.
- **`test_*.py`** -- اختبارات لكل جزء من النظام.

---

## 4. شرح الكود بالتفصيل

### 4.1 ملف `app/main.py` -- نقطة البداية

هذا الملف ينشئ تطبيق FastAPI ويهيئ كل شيء.

```python
from __future__ import annotations
```
هذا السطر يجعل Python يعامل كل الـ type annotations كـ strings. هذا يحل مشاكل الإشارة الدائرية (circular imports) في الأنواع ويعمل مع الإصدارات الأقدم من Python.

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
```
هذه **دالة دورة الحياة** (Lifespan function). تُنفذ عندما يبدأ التطبيق (startup) وعندما يتوقف (shutdown). كل ما قبل `yield` يحدث عند البداية، وكل ما بعده يحدث عند الإيقاف.

**ما يحدث عند البداية:**

```python
settings = get_settings()
```
يقرأ الإعدادات من متغيرات البيئة. `get_settings()` مزخرفة بـ `@lru_cache` مما يعني أنها تُنشئ كائن `Settings` مرة واحدة فقط وتعيد نسخته في كل مرة تُستدعى. هذا يسمى **Singleton pattern** -- نريد نسخة واحدة فقط من الإعدادات.

```python
llm_client = create_llm_client(settings)
app.state.llm_client = llm_client
```
ينشئ عميل الذكاء الاصطناعي (حسب `LLM_PROVIDER` في الإعدادات) ويخزنه في `app.state`. هذا كائن FastAPI خاص مصمم لتخزين الكائنات المشتركة بين الطلبات.

```python
cat_mapper = CategoryMapper(...)
cat_mapper.load()
```
ينشئ مصنّف الفئات ويحمّل الكلمات المفتاحية من ملف CSV. هذا يحدث مرة واحدة عند البداية لأن قراءة الملف بطيئة -- لا نريد قراءته مع كل طلب.

```python
registry = StepRegistry()
registry.register(CaptureStep(capture_service))
registry.register(MappingStep(mapper_service))
pipeline = PipelineOrchestrator(registry)
```
ينشئ الخط الإنتاجي (Pipeline): سجل الخطوات، يسجل الخطوتين (Capture ثم Mapping) بالترتيب، ثم ينشئ المنظم.

**دالة `create_app()`:**

```python
def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
```
تنشئ كائن FastAPI مع عنوان التطبيق والإصدار وروابط التوثيق التلقائي. `docs_url="/docs"` يعني أنك تستطيع فتح `http://localhost:8090/docs` في المتصفح ورؤية واجهة Swagger التفاعلية.

```python
app.add_middleware(CORSMiddleware, ...)
app.add_middleware(RequestIDMiddleware)
```
يضيف طبقتين وسيطتين:
- **CORS** -- تسمح لمتصفحات الويب بالوصول للـ API من نطاقات مختلفة.
- **Request ID** -- تولّد معرّف فريد لكل طلب (شرحناها أعلاه).

**ملاحظة مهمة:** ترتيب `add_middleware` عكسي. آخر middleware يُضاف هو أول من يعالج الطلب. لذلك `RequestIDMiddleware` يُنفذ أولاً (يولّد الـ ID)، ثم `CORSMiddleware`.

```python
app.add_exception_handler(AIServiceError, ai_service_error_handler)
app.add_exception_handler(Exception, generic_error_handler)
```
يسجل معالجات الأخطاء. إذا رمى أي كود `AIServiceError` (أو أي فئة فرعية منه)، يُعالج بدالة مخصصة ترجع JSON منظم. أي خطأ آخر يُعالج بالدالة العامة التي ترجع 500.

```python
app = create_app()
```
السطر الأخير في الملف. ينشئ التطبيق فعلياً. عندما يشغّل Uvicorn `app.main:app`، يبحث عن متغير اسمه `app` في هذا الملف.

### 4.2 ملف `app/core/config.py` -- الإعدادات

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
```

`BaseSettings` من مكتبة `pydantic-settings` يقرأ القيم تلقائياً من:
1. متغيرات البيئة (Environment Variables) -- الأولوية الأعلى
2. ملف `.env` -- إذا لم يوجد متغير بيئة

`extra="ignore"` يعني: إذا كان في `.env` متغير لا يوجد له حقل في `Settings`، تجاهله بدلاً من رمي خطأ.

```python
LLM_PROVIDER: Literal["vertex", "openai"] = "vertex"
```
هذا حقل من نوع `Literal` -- يعني أن القيمة يجب أن تكون إحدى القيم المذكورة فقط. إذا وضعت `LLM_PROVIDER=azure` في `.env`، Pydantic يرفض ويرمي خطأ عند بدء التطبيق. هذا يمنع الأخطاء المطبعية.

```python
@lru_cache
def get_settings() -> Settings:
    return Settings()
```
`@lru_cache` هو **مزخرف** (Decorator) من مكتبة `functools`. يحفظ نتيجة أول استدعاء للدالة في الذاكرة. كل استدعاء لاحق يعيد نفس النتيجة بدون إعادة إنشاء كائن `Settings`. هذا يضمن أن كل الكود يستخدم نفس نسخة الإعدادات.

### 4.3 ملف `app/core/exceptions.py` -- هرمية الأخطاء

```python
class AIServiceError(Exception):
    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        self.message = message
        self.details = details or {}
        super().__init__(message)
```

هذا هو **الخطأ الجذر** (Root Exception). كل أنواع الأخطاء المخصصة ترث منه. له:
- `status_code` -- رمز HTTP الذي سيُرجع للعميل (500 افتراضياً)
- `error_code` -- رمز نصي فريد يستخدمه العميل لتحديد نوع الخطأ برمجياً
- `message` -- رسالة نصية مقروءة للبشر
- `details` -- معلومات إضافية (اختيارية)

**لماذا نستخدم هرمية؟** لأن Python يدعم `except` بحسب نوع الخطأ:
- `except AIServiceError` -- يلتقط كل الأخطاء المخصصة
- `except LLMError` -- يلتقط فقط أخطاء الذكاء الاصطناعي
- `except PDFError` -- يلتقط فقط أخطاء PDF

### 4.4 ملف `app/services/llm/base.py` -- واجهة LLM المجردة

```python
class BaseLLMClient(ABC):
    @abstractmethod
    async def generate(self, prompt: str, content: str | None = None, *,
                       config: GenerationConfig | None = None, label: str = "") -> LLMResponse:
        ...

    @abstractmethod
    async def generate_from_pdf(self, prompt: str, pdf_bytes: bytes, *,
                                 config: GenerationConfig | None = None, label: str = "") -> LLMResponse:
        ...
```

**ما هو `ABC`؟** هو اختصار لـ Abstract Base Class. الـ class الذي يرث من `ABC` لا يمكن إنشاء كائن منه مباشرة. يجب على الفئات الفرعية تطبيق كل الدوال المعلّمة بـ `@abstractmethod`.

**ما معنى `*` في المعاملات؟** كل ما بعد `*` هو **keyword-only arguments** -- يجب تمريرها بالاسم، مثل `config=GenerationConfig()`. هذا يمنع الأخطاء عند تغيير ترتيب المعاملات.

**`GenerationConfig`:**
```python
@dataclass(frozen=True)
class GenerationConfig:
    max_output_tokens: int = 8192
    temperature: float = 0.1
    response_json: bool = True
```
`frozen=True` يعني أن الكائن **غير قابل للتغيير** (Immutable) بعد إنشائه. هذا يمنع الأخطاء حيث يغير كود ما قيمة التكوين عن طريق الخطأ.

`temperature` هو مقياس "الإبداع" في نموذج الذكاء الاصطناعي: `0.0` = حتمي تماماً (نفس المدخل = نفس المخرج)، `1.0` = عشوائي جداً. نستخدم `0.1` لأننا نريد استخراج بيانات دقيقة، لا نص إبداعي.

### 4.5 ملف `app/services/llm/vertex.py` -- عميل Gemini

هذا أطول ملف في المشروع. دعنا نشرح الأجزاء المهمة:

**التهيئة الكسولة (Lazy Initialization):**
```python
def _ensure_init(self) -> None:
    if not self._initialized:
        vertexai.init(project=..., location=...)
        self._initialized = True
```
لا نتصل بـ Google Cloud إلا عندما نحتاج فعلاً. هذا يجعل بدء التطبيق أسرع ويتجنب أخطاء الشبكة عند البدء.

**تنفيذ الاستدعاء المتزامن في سلسلة تنفيذ (Thread Executor):**
```python
loop = asyncio.get_running_loop()
response = await loop.run_in_executor(
    None,
    lambda: model.generate_content(content_parts, generation_config=v_config),
)
```
هنا المشكلة: Vertex AI SDK متزامن (synchronous) -- يحجب السلسلة الحالية حتى يأتي الرد. لكن FastAPI غير متزامن (asynchronous) -- إذا حجزنا حلقة الأحداث (Event Loop)، لن نتمكن من معالجة طلبات أخرى.

الحل: `run_in_executor(None, ...)` ينفذ الدالة المتزامنة في سلسلة تنفيذ منفصلة (Thread Pool)، بينما حلقة الأحداث الرئيسية تبقى حرة لمعالجة طلبات أخرى. `None` يعني "استخدم Thread Pool الافتراضي".

**إعادة المحاولة بتراجع أسّي (Exponential Backoff):**
```python
def _delay(self, attempt: int) -> float:
    base = min(s.LLM_BASE_DELAY * (2 ** attempt), s.LLM_MAX_DELAY)
    jitter = random.uniform(0, base * s.LLM_JITTER_FACTOR)
    return base + jitter
```
إذا فشل الاستدعاء (لأن Google مشغولة مثلاً)، ننتظر قبل إعادة المحاولة. مدة الانتظار تتضاعف مع كل محاولة:
- المحاولة 1: ~1 ثانية
- المحاولة 2: ~2 ثانية
- المحاولة 3: ~4 ثوانٍ
- المحاولة 4: ~8 ثوانٍ

**الـ Jitter** (التذبذب العشوائي) يضيف عنصر عشوائية. لماذا؟ تخيل 100 طلب فشلت كلها في نفس الوقت. بدون jitter، كلها ستعيد المحاولة بعد ثانية واحدة بالضبط -- مما يخلق "موجة" ثانية تغرق الخادم. مع jitter، المحاولات تتوزع على فترة، مما يقلل الحمل.

**تنظيف مخرجات JSON:**
```python
@staticmethod
def _parse_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
```
أحياناً نموذج الذكاء الاصطناعي يلف الـ JSON في علامات markdown مثل ` ```json ... ``` `. هذا الكود ينظفها قبل التحليل.

### 4.6 ملف `app/services/capture/capture_service.py` -- خدمة OCR

```python
_CAPTURE_PROMPT: str | None = None

def _get_capture_prompt() -> str:
    global _CAPTURE_PROMPT
    if _CAPTURE_PROMPT is None:
        schema = SchemaValidator.load_raw_schema("capture_output")
        schema_str = json.dumps(schema, indent=2)
        _CAPTURE_PROMPT = f"""You are a document OCR and extraction expert..."""
    return _CAPTURE_PROMPT
```

**ما هو `global`؟** يعني أن المتغير `_CAPTURE_PROMPT` معرّف على مستوى الوحدة (Module level)، ليس داخل الدالة. `global` يخبر Python أننا نريد تعديل المتغير الخارجي، لا إنشاء متغير محلي.

**لماذا التحميل الكسول؟** الـ Prompt يتضمن مخطط JSON Schema كاملاً (يُقرأ من ملف). بدلاً من قراءة الملف مع كل طلب، نقرأه مرة واحدة ونحفظه.

**عملية OCR:**
```python
async def process(self, pdf_bytes, page_numbers=None):
    total_pages = LayoutService.get_page_count(pdf_bytes)    # 1. عد الصفحات

    if page_numbers is None:
        page_numbers = list(range(1, total_pages + 1))       # 2. كل الصفحات

    if len(page_numbers) < total_pages:
        extracted_pdf = LayoutService.extract_pages_to_bytes(pdf_bytes, page_numbers)
    else:
        extracted_pdf = pdf_bytes                             # 3. استخراج الصفحات

    response = await self._llm.generate_from_pdf(
        prompt=_get_capture_prompt(),
        pdf_bytes=extracted_pdf,
        label="capture_ocr",
    )                                                         # 4. إرسال لـ Gemini

    is_valid, errors = SchemaValidator.validate("capture_output", ocr_output)
    if not is_valid:
        raise SchemaValidationError(...)                      # 5. التحقق

    self._map_pages(pages, page_numbers)
    self._map_tables(tables, page_numbers)                    # 6. ربط أرقام الصفحات
```

**لماذا `_map_pages`؟** عندما نستخرج صفحات 5, 6, 7 من مستند 50 صفحة، نرسل لـ Gemini ملف PDF من 3 صفحات. Gemini يرقمها 1, 2, 3. لكننا نحتاج أن نعرف أن "صفحة 1" في مخرجات Gemini هي في الحقيقة "صفحة 5" في المستند الأصلي. `_map_pages` تضيف `original_page_number` لكل صفحة.

### 4.7 ملف `app/services/mapping/financial_mapper.py` -- المراحل الأربع

**المرحلة 3 -- المعالجة المتوازية:**
```python
async def _run_pass_3(self, ocr_data, pass_2):
    statements = pass_2.get("statements", [])
    non_notes = [s for s in statements if s.get("statement_type") != "NOTES"]

    tasks = [self._process_statement(ocr_data, stmt) for stmt in non_notes]
    results = await asyncio.gather(*tasks, return_exceptions=True)
```

هذا أهم جزء في الأداء. `asyncio.gather()` يشغّل عدة coroutines **بالتوازي**:
- بدون `gather`: إذا كان هناك 4 قوائم مالية، كل واحدة تستغرق 15 ثانية = 60 ثانية إجمالي.
- مع `gather`: كل الـ 4 تعمل في نفس الوقت = ~15 ثانية إجمالي.

`return_exceptions=True` يعني: إذا فشلت واحدة من المهام، لا توقف الباقي. بدلاً من ذلك، ارجع الخطأ كنتيجة. بعد ذلك نتحقق:
```python
for stmt_info, result in zip(non_notes, results):
    if isinstance(result, BaseException):
        raise PassExecutionError(...)
```

**السياق المحسّن لكل قائمة:**
```python
tables = self._tables_for_pages(ocr_data, start, end, stmt_info.get("table_ids", []))
text = self._text_for_pages(ocr_data, start, end)
```
بدلاً من إرسال كل الجداول والنصوص لكل استدعاء LLM (مما يهدر Tokens ويزيد الهلوسة)، نرسل فقط الجداول والنصوص المتعلقة بالقائمة المالية المحددة.

### 4.8 ملف `app/pipeline/orchestrator.py` -- المنظم

```python
async def run(self, initial_data=None):
    ctx = PipelineContext(data=dict(initial_data or {}))
    steps = self._registry.ordered_steps

    for step in steps:
        if not await step.validate_input(ctx):
            raise StepError(step.name, "Input validation failed")

        result = await step.execute(ctx)

        if not result.success:
            raise StepError(step.name, result.error)

    return {**ctx.data, "_pipeline_metadata": {...}}
```

هذا **نمط المنظم** (Orchestrator Pattern). المنظم لا يعرف ماذا تفعل كل خطوة -- فقط يعرف كيف ينفذها بالتتابع. كل خطوة:
1. **تتحقق من مدخلاتها** -- هل البيانات المطلوبة موجودة في السياق؟
2. **تنفذ** -- تقرأ من السياق، تعمل، تكتب نتائجها في السياق.
3. **ترجع نتيجة** -- نجاح أو فشل.

**`PipelineContext`** هو كائن مشترك بين كل الخطوات. الخطوة الأولى (Capture) تكتب `capture_output` في السياق. الخطوة الثانية (Mapping) تقرأ `capture_output` من السياق. هذا يسمى **Blackboard pattern** -- لوحة سوداء مشتركة يكتب عليها الجميع ويقرأ منها الجميع.

### 4.9 ملف `app/api/deps.py` -- حقن التبعيات

```python
def get_llm_client(request: Request) -> BaseLLMClient:
    return request.app.state.llm_client
```

هذه دوال بسيطة تسترجع الكائنات من `app.state`. في الـ endpoint:
```python
async def run_capture(
    service: CaptureService = Depends(get_capture_service),
):
```

`Depends(get_capture_service)` يخبر FastAPI: "قبل تنفيذ هذا الـ endpoint، استدعِ `get_capture_service()` ومرر النتيجة كمعامل `service`." هذا يسمى **Dependency Injection** -- الـ endpoint لا ينشئ خدماته بنفسه، بل يستقبلها من الخارج.

**لماذا هذا مهم؟** في الاختبارات، يمكننا استبدال الخدمة الحقيقية بخدمة وهمية (Fake) بدون تغيير كود الـ endpoint.

### 4.10 ملف `app/middleware/request_id.py` -- معرّف الطلب

```python
class RequestIDMiddleware:
    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        request_id = _extract_request_id(scope) or str(uuid.uuid4())

        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            async def send_with_id(message):
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers", []))
                    headers.append((HEADER_NAME, request_id.encode()))
                    message["headers"] = headers
                await send(message)

            await self.app(scope, receive, send_with_id)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
```

هذا **ASGI Middleware** -- يتبع بروتوكول ASGI مباشرة (بدون طبقة تجريد مثل `BaseHTTPMiddleware`).

`scope` -- قاموس يحتوي معلومات الطلب (نوعه، headers، path).
`receive` -- دالة لاستقبال بيانات الطلب.
`send` -- دالة لإرسال الاستجابة.

`structlog.contextvars.bind_contextvars(request_id=...)` يربط المعرّف بـ **Context Variables**. هذه ميزة في Python تسمح لمتغير أن يكون مرتبطاً بالـ coroutine الحالي. كل سجل (log) يُكتب أثناء معالجة هذا الطلب سيحتوي تلقائياً على `request_id`.

---

## 5. شرح المكتبات المستخدمة

### FastAPI

**ما هي؟** إطار عمل حديث لبناء APIs في Python. مبني على Starlette (للشبكة) و Pydantic (للتحقق من البيانات).

**لماذا اخترناها؟**
- **سرعة أداء** -- من أسرع أطر عمل Python (مقارنة بـ Flask و Django REST).
- **Async بالطبيعة** -- تدعم `async/await` مما يسمح بمعالجة طلبات متعددة بكفاءة.
- **توثيق تلقائي** -- تولّد Swagger UI وReDoc تلقائياً من الكود.
- **Pydantic مدمج** -- التحقق من المدخلات والمخرجات تلقائي.

**البديل:** Flask -- أبسط لكن متزامن (synchronous) ولا يدعم async بشكل أصلي. Django REST Framework -- قوي لكن ثقيل لخدمة مصغرة.

### Pydantic و pydantic-settings

**ما هي؟** مكتبة للتحقق من البيانات وتحويلها (Data Validation and Parsing).

**لماذا؟** تضمن أن البيانات الداخلة والخارجة من الـ API صحيحة. بدلاً من كتابة:
```python
if "name" not in data or not isinstance(data["name"], str):
    raise ValueError("name is required")
```
تكتب:
```python
class User(BaseModel):
    name: str
```
و Pydantic تفعل كل التحقق تلقائياً.

`pydantic-settings` توسيع يقرأ القيم من متغيرات البيئة تلقائياً.

### Uvicorn

**ما هو؟** خادم ASGI سريع. يشغّل تطبيق FastAPI ويستمع للطلبات على منفذ محدد.

**العلاقة:** FastAPI = التطبيق. Uvicorn = الخادم الذي يشغّل التطبيق. مثل العلاقة بين برنامج وجهاز الكمبيوتر.

### google-cloud-aiplatform (Vertex AI SDK)

**ما هي؟** مكتبة Google الرسمية للتواصل مع خدمات Vertex AI، بما فيها نماذج Gemini.

**لماذا؟** هي الطريقة الوحيدة المدعومة رسمياً للتواصل مع Gemini عبر Vertex AI. تتعامل مع المصادقة (Authentication) والشبكة تلقائياً.

### PyMuPDF (fitz)

**ما هي؟** مكتبة لمعالجة ملفات PDF. اسمها في الكود `fitz` (من اسم المحرك الداخلي MuPDF).

**لماذا؟** نحتاجها لـ:
- عد صفحات PDF
- استخراج صفحات محددة من PDF كبير
- التحقق أن الملف المرفوع هو PDF صالح

**البديل:** `PyPDF2` -- أبسط لكن أبطأ وأقل ميزات. `pdfplumber` -- جيد لاستخراج الجداول لكن لا يدعم إنشاء ملفات PDF جديدة.

### jsonschema

**ما هي؟** مكتبة للتحقق من بيانات JSON مقابل مخطط (JSON Schema).

**لماذا؟** نماذج الذكاء الاصطناعي غير حتمية -- قد ترجع JSON بحقول ناقصة أو أنواع خاطئة. نستخدم JSON Schema للتحقق أن المخرجات تطابق ما نتوقعه قبل إرسالها للعميل.

### structlog

**ما هي؟** مكتبة للتسجيل المنظم (Structured Logging).

**لماذا؟** بدلاً من سجلات نصية مثل:
```
INFO: Processing file document.pdf with 10 pages
```
تنتج سجلات JSON مثل:
```json
{"event": "capture_ocr_start", "pages": [1,2,3], "request_id": "abc-123", "timestamp": "2026-04-07T10:30:00"}
```
السجلات المنظمة يمكن تصفيتها والبحث فيها تلقائياً بأدوات مثل CloudWatch أو Elasticsearch.

### httpx

**ما هي؟** عميل HTTP حديث يدعم async و sync.

**لماذا؟** نستخدمها لـ:
- جلب ملف CSV من الإنترنت (Category Mapper)
- في الاختبارات: إرسال طلبات HTTP وهمية لتطبيق FastAPI

### pytest و pytest-asyncio

**ما هي؟** إطار عمل لكتابة وتشغيل الاختبارات. `pytest-asyncio` يضيف دعم `async/await` للاختبارات.

**لماذا pytest بدلاً من unittest؟** أبسط (لا تحتاج classes)، ميزة Fixtures أقوى، والمجتمع أكبر.

### asyncio (مكتبة قياسية)

**ما هي؟** مكتبة Python القياسية للبرمجة غير المتزامنة (Asynchronous Programming).

**المفاهيم الرئيسية:**
- **Coroutine** -- دالة معرّفة بـ `async def`. لا تنفذ فوراً عند استدعائها -- ترجع كائن coroutine يمكن تنفيذه لاحقاً.
- **await** -- تعليق تنفيذ الـ coroutine الحالي حتى ينتهي الـ coroutine الآخر. أثناء التعليق، حلقة الأحداث تشغّل coroutines أخرى.
- **Event Loop** -- حلقة الأحداث التي تنظم تنفيذ الـ coroutines.
- **gather()** -- تشغيل عدة coroutines بالتوازي.

---

## 6. الأنماط والمفاهيم المستخدمة

### حقن التبعيات (Dependency Injection)

**المفهوم:** بدلاً من أن يُنشئ الكائن تبعياته بنفسه، يستقبلها من الخارج.

**بدون DI:**
```python
class CaptureService:
    def __init__(self):
        self.llm = VertexLLMClient(Settings())  # مربوط بتطبيق محدد
```

**مع DI:**
```python
class CaptureService:
    def __init__(self, llm_client: BaseLLMClient):  # يستقبل أي تطبيق
        self._llm = llm_client
```

في الإنتاج: `CaptureService(VertexLLMClient(settings))`
في الاختبارات: `CaptureService(FakeLLMClient())`

### نمط المنظم (Orchestrator Pattern)

**المفهوم:** كائن مركزي (المنظم) ينسّق تنفيذ عمليات متعددة بدون أن يعرف تفاصيل كل عملية.

في مشروعنا: `PipelineOrchestrator` لا يعرف كيف يعمل OCR أو Mapping. فقط يعرف أن هناك خطوات مسجلة، كل خطوة لديها `validate_input()` و `execute()`.

### نمط الخط الإنتاجي (Pipeline Pattern)

**المفهوم:** سلسلة من المراحل، كل مرحلة تأخذ مخرجات المرحلة السابقة كمدخلات.

```
PDF → [Capture] → OCR Data → [Mapping] → Financial Structure
```

كل خطوة مستقلة: يمكنك اختبارها بمفردها، استبدالها، أو إضافة خطوات جديدة.

### المعالجة المتوازية (Parallel Processing)

في المرحلة الثالثة من Mapping، كل قائمة مالية (ميزانية، دخل، تدفقات نقدية) تُعالج بالتوازي باستخدام `asyncio.gather()`.

**كيف يعمل هذا؟** كل استدعاء لـ Gemini ينتظر ردّاً عبر الشبكة. بدلاً من الانتظار واحداً تلو الآخر، نرسل كل الطلبات معاً وننتظرها كلها. حلقة الأحداث تنتقل بين المهام أثناء انتظار كل واحدة.

### Async مقابل Threading

**Async** -- حلقة أحداث واحدة تنتقل بين المهام عند نقاط الانتظار (`await`). مناسب لعمليات I/O (شبكة، ملفات).

**Threading** -- سلاسل تنفيذ متعددة تعمل فعلاً بالتوازي. مناسب لعمليات حسابية كثيفة (CPU-bound).

في مشروعنا نستخدم **كلاهما**:
- Async لتنسيق الطلبات والانتظار.
- Threading (عبر `run_in_executor`) لتشغيل Vertex AI SDK المتزامن بدون حجز حلقة الأحداث.

### التحقق بالمخطط (Schema Validation)

بعد كل استدعاء LLM، نتحقق أن المخرجات تطابق JSON Schema محدد. هذا ضروري لأن:
1. نماذج الذكاء الاصطناعي قد تنسى حقولاً.
2. قد ترجع أنواع خاطئة (نص بدلاً من رقم).
3. قد تضيف حقولاً غير متوقعة.

إذا فشل التحقق، نرمي خطأ واضح بدلاً من ترك بيانات فاسدة تنتشر في النظام.

### نمط المصنع (Factory Pattern)

```python
def create_llm_client(settings: Settings) -> BaseLLMClient:
    provider = settings.LLM_PROVIDER.lower()
    if provider == "vertex":
        return VertexLLMClient(settings)
    raise ValueError(f"Unsupported LLM provider: {provider}")
```

المصنع يقرر أي class يُنشئ بناءً على الإعدادات. الكود الذي يستدعي المصنع لا يعرف (ولا يحتاج أن يعرف) أي تطبيق يُستخدم.

---

## 7. شرح الاختبارات

### ما هو pytest؟

pytest هو إطار عمل لكتابة اختبارات في Python. يبحث تلقائياً عن ملفات تبدأ بـ `test_` ودوال تبدأ بـ `test_` ويشغلها.

### ما هو Fixture؟

**Fixture** هو "إعداد مسبق" للاختبار. بدلاً من تكرار كود الإعداد في كل اختبار، تكتبه مرة واحدة كـ fixture وتستخدمه في أي اختبار.

```python
@pytest.fixture
def fake_llm() -> FakeLLMClient:
    return FakeLLMClient()
```

**ما هو `@pytest.fixture`؟** هذا **مزخرف** (Decorator). المزخرف هو دالة تأخذ دالة أخرى وتضيف لها سلوكاً جديداً. `@pytest.fixture` يقول لـ pytest: "هذه الدالة ليست اختباراً -- إنها إعداد. عندما يحتاجها اختبار ما، شغّلها وأعطه النتيجة."

**كيف يستخدمها الاختبار:**
```python
async def test_capture_service(fake_llm: FakeLLMClient, sample_pdf_bytes: bytes):
    # fake_llm و sample_pdf_bytes تُحقن تلقائياً من الـ fixtures
```

pytest يرى أن الاختبار يحتاج `fake_llm` و `sample_pdf_bytes`، فيبحث عن fixtures بهذه الأسماء ويستدعيها.

### Fixture مثال: `sample_pdf_bytes`

```python
@pytest.fixture
def sample_pdf_bytes() -> bytes:
    import io
    import fitz

    doc = fitz.open()                                    # إنشاء PDF فارغ
    page = doc.new_page(width=595, height=842)           # إضافة صفحة (A4)
    page.insert_text((72, 72), "Sample financial statement text")  # كتابة نص
    buf = io.BytesIO()                                   # منطقة ذاكرة
    doc.save(buf)                                        # حفظ PDF في الذاكرة
    doc.close()
    return buf.getvalue()                                # إرجاع البايتات
```

**لماذا نرجع `bytes`؟** لأن الـ API يستقبل ملف PDF كـ bytes (عبر `UploadFile`). في الاختبار، بدلاً من قراءة ملف حقيقي من القرص، ننشئ PDF وهمي في الذاكرة.

### FakeLLMClient -- العميل الوهمي

```python
class FakeLLMClient(BaseLLMClient):
    def __init__(self):
        self._responses: dict[str, dict[str, Any]] = {}
        self._default_response: dict[str, Any] = {"status": "ok"}
        self.calls: list[dict[str, Any]] = []

    def set_response(self, label: str, data: dict[str, Any]) -> None:
        self._responses[label] = data
```

هذا **كائن وهمي** (Stub/Fake). يطبّق نفس الواجهة (`BaseLLMClient`) لكن بدلاً من الاتصال بـ Google، يرجع بيانات محددة مسبقاً.

في الاختبار:
```python
fake_llm.set_response("capture_ocr", {"raw_text": "Test", "pages": [...], ...})
```
الآن عندما يستدعي `CaptureService` الدالة `generate_from_pdf` بـ label `"capture_ocr"`، يحصل على البيانات التي حددناها -- بدون أي اتصال بالإنترنت.

### `async_client` -- عميل HTTP للاختبار

```python
@pytest_asyncio.fixture
async def async_client(fake_llm: FakeLLMClient) -> AsyncIterator[AsyncClient]:
    app = create_app()

    app.state.llm_client = fake_llm
    app.state.capture_service = CaptureService(fake_llm)
    # ... إعداد بقية الخدمات ...

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
```

هذا ينشئ عميل HTTP يرسل الطلبات مباشرة لتطبيق FastAPI **بدون شبكة فعلية**. `ASGITransport` يوجّه الطلبات داخلياً. هذا أسرع بكثير من تشغيل خادم حقيقي.

### تشغيل الاختبارات

```bash
cd ai-service

# تشغيل كل الاختبارات
pytest tests/ -v

# تشغيل مع تقرير التغطية
pytest tests/ -v --cov=app --cov-report=term-missing

# تشغيل ملف واحد
pytest tests/test_capture.py -v

# تشغيل اختبار واحد
pytest tests/test_api.py::test_health_endpoint -v
```

`-v` = verbose (عرض تفاصيل كل اختبار)
`--cov=app` = حساب تغطية الكود (أي أسطر الكود تم اختبارها)

---

## 8. تدفق النظام من البداية للنهاية

### الخطوة 1: بدء التطبيق

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8090
```

1. Uvicorn يقرأ `app.main:app` -- يستورد الوحدة `app.main` ويأخذ المتغير `app`.
2. `create_app()` يُنشئ كائن FastAPI مع الـ middleware والـ exception handlers والـ routers.
3. عندما يبدأ Uvicorn بالاستماع، يُنفذ `lifespan()` (الجزء قبل `yield`).
4. يتم إنشاء كل الخدمات وتخزينها في `app.state`.
5. التطبيق جاهز لاستقبال الطلبات.

### الخطوة 2: إرسال طلب (مثال: Pipeline)

العميل (Django/Celery) يرسل:
```
POST /api/v1/pipeline/execute
Content-Type: multipart/form-data

file: [بايتات PDF]
config: {"page_numbers": [5,6,7,8], "apply_category_mapping": true}
```

### الخطوة 3: معالجة الطلب

```
1. RequestIDMiddleware
   → يولّد request_id = "abc-123"
   → يربطه بـ structlog contextvars
   → يضيفه لـ response headers

2. CORSMiddleware
   → يتحقق من Origin header
   → يضيف CORS headers

3. FastAPI Router
   → يطابق URL: /api/v1/pipeline/execute → pipeline.py:execute_pipeline()

4. Dependency Injection
   → get_settings() → Settings(...)
   → get_pipeline() → PipelineOrchestrator من app.state

5. execute_pipeline()
   → يقرأ PDF bytes
   → يتحقق من الحجم (< 50 MB)
   → يحلل config JSON
   → يستدعي pipeline.run(initial_data)

6. PipelineOrchestrator.run()
   → ينشئ PipelineContext مع {pdf_bytes, page_numbers, ...}
   → يبدأ CaptureStep:
      → validate_input: هل pdf_bytes موجود؟ ✓
      → execute:
         → CaptureService.process()
            → LayoutService.get_page_count() → 50 صفحة
            → LayoutService.extract_pages_to_bytes([5,6,7,8]) → PDF جديد 4 صفحات
            → VertexLLMClient.generate_from_pdf() → يرسل لـ Gemini
               → _call_with_retry() → محاولة 1 → نجاح!
               → يحلل JSON من الرد
            → SchemaValidator.validate() → المخرجات صحيحة ✓
            → _map_pages() → يربط الصفحات بالأرقام الأصلية
         → context.set("capture_output", result)
      → StepResult(success=True)

   → يبدأ MappingStep:
      → validate_input: هل capture_output موجود ومليء؟ ✓
      → execute:
         → FinancialMapperService.process()
            → Pass 1: استخراج metadata (اسم الشركة، العملة، الفترات)
            → Pass 2: تحديد القوائم المالية ونطاق صفحاتها
            → Pass 3: استخراج بنود كل قائمة (بالتوازي!)
               → asyncio.gather(
                    _process_statement(BALANCE_SHEET),
                    _process_statement(INCOME_STATEMENT),
                    _process_statement(CASH_FLOW),
                  )
            → CategoryMapper.categorize_items() → تصنيف البنود
            → Pass 4: استخراج الملاحظات
         → context.set("mapping_output", result)
      → StepResult(success=True)

   → يرجع {capture_output, mapping_output, _pipeline_metadata}

7. execute_pipeline()
   → يغلّف النتيجة في PipelineResponse
   → FastAPI يحوّل Pydantic model إلى JSON
   → يرجع HTTP 200 مع الـ JSON

8. RequestIDMiddleware
   → يضيف X-Request-ID: abc-123 للـ response headers
   → يمسح request_id من contextvars
```

---

## 9. كيفية تشغيل المشروع

### الطريقة الأولى: محلياً (بدون Docker)

**المتطلبات:**
- Python 3.11 أو أحدث
- حساب Google Cloud مع Vertex AI مفعّل

**الخطوة 1: إنشاء بيئة افتراضية**

```bash
cd ai-service

# إنشاء البيئة
python -m venv venv

# تفعيلها
# Linux / macOS:
source venv/bin/activate
# Windows (PowerShell):
.\venv\Scripts\Activate.ps1
```

**ما هي البيئة الافتراضية (Virtual Environment)؟** مجلد يحتوي نسخة معزولة من Python ومكتباتها. كل مشروع لديه بيئته الخاصة حتى لا تتعارض المكتبات بين المشاريع.

**الخطوة 2: تثبيت المكتبات**

```bash
pip install -r requirements.txt
```

هذا يقرأ ملف `requirements.txt` ويثبّت كل المكتبات المذكورة فيه.

**الخطوة 3: إعداد متغيرات البيئة**

```bash
cp .env.example .env
```

ثم افتح `.env` وعدّل على الأقل:
```
GOOGLE_CLOUD_PROJECT_ID=your-actual-project-id
ENVIRONMENT=development
```

**الخطوة 4: المصادقة مع Google Cloud**

```bash
gcloud auth application-default login
```

هذا يفتح المتصفح لتسجيل الدخول ويحفظ بيانات الاعتماد محلياً.

**الخطوة 5: تشغيل الخادم**

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8090
```

`--reload` يعيد التشغيل تلقائياً عند تغيير الكود (للتطوير فقط).

**الخطوة 6: التحقق**

```bash
curl http://localhost:8090/api/v1/health
```

يجب أن ترى:
```json
{"status": "ok", "version": "1.0.0", "environment": "development"}
```

### الطريقة الثانية: باستخدام Docker

**الخطوة 1: إنشاء شبكة Docker**

```bash
docker network create mala_network
```

**الخطوة 2: إعداد `.env`**

```bash
cd ai-service
cp .env.example .env
# عدّل GOOGLE_CLOUD_PROJECT_ID
```

**الخطوة 3: بناء وتشغيل**

```bash
docker compose up --build
```

لتشغيل في الخلفية:
```bash
docker compose up --build -d
```

**الخطوة 4: التحقق**

```bash
curl http://localhost:8090/api/v1/health
```

**الخطوة 5: عرض السجلات**

```bash
docker compose logs -f ai-service
```

**الخطوة 6: الإيقاف**

```bash
docker compose down
```

### شرح Dockerfile

```dockerfile
# ---- مرحلة البناء ----
FROM python:3.11-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt
```

المرحلة الأولى تثبّت المكتبات فقط. نفصلها لأن:
- إذا لم يتغير `requirements.txt`، Docker يستخدم الذاكرة المخبأة (Cache) ولا يعيد التثبيت.
- الصورة النهائية لا تحتوي أدوات البناء (مثل `gcc`)، مما يجعلها أصغر وأكثر أماناً.

```dockerfile
# ---- مرحلة التشغيل ----
FROM python:3.11-slim
RUN groupadd --gid 1000 appgroup \
    && useradd --uid 1000 --gid appgroup --shell /bin/bash --create-home appuser
USER appuser
```

ننشئ مستخدماً غير جذري (non-root) ونشغل التطبيق كـ `appuser`. إذا اختُرق التطبيق، المهاجم لا يملك صلاحيات الجذر (root).

---

## 10. كيفية اختبار المشروع

### اختبار فحص الصحة

```bash
curl -s http://localhost:8090/api/v1/health | python -m json.tool
```

### اختبار OCR (رفع ملف)

```bash
curl -X POST http://localhost:8090/api/v1/capture \
  -F "file=@/path/to/financial_statement.pdf" \
  -F 'page_numbers=[5,6,7,8]'
```

**شرح:**
- `-X POST` -- نوع الطلب: POST
- `-F "file=@..."` -- رفع ملف (multipart/form-data). `@` تعني "اقرأ من هذا المسار"
- `-F 'page_numbers=[5,6,7,8]'` -- حقل نصي يحتوي JSON array

**الاستجابة المتوقعة:**
```json
{
  "raw_text": "Statement of Financial Position...",
  "pages": [
    {"page_number": 1, "text": "...", "original_page_number": 5}
  ],
  "tables": [...],
  "detected_language": "ar-en",
  "page_count": 4,
  "is_schema_valid": true,
  "metadata": {
    "model": "gemini-1.5-pro-002",
    "processing_time_ms": 12000
  }
}
```

### اختبار التحليل المالي

```bash
curl -X POST http://localhost:8090/api/v1/mapping \
  -H "Content-Type: application/json" \
  -d '{
    "ocr_data": {
      "raw_text": "Statement of Financial Position...",
      "pages": [{"page_number": 1, "text": "...", "original_page_number": 5}],
      "tables": [{"page": 1, "table_id": "t1", "headers": ["Item","2024","2023"], "rows": [["Cash","1500000","1200000"]]}],
      "detected_language": "en"
    },
    "options": {"apply_category_mapping": true}
  }'
```

### اختبار الخط الإنتاجي الكامل

```bash
curl -X POST http://localhost:8090/api/v1/pipeline/execute \
  -F "file=@/path/to/report.pdf" \
  -F 'config={"page_numbers": [5,6,7,8], "apply_category_mapping": true}'
```

### اختبار باستخدام Postman

المشروع يحتوي على مجلد `postman/` يتضمن:
- `Financial_AI_Service.postman_collection.json` -- مجموعة الطلبات
- `Financial_AI_Service.postman_environment.json` -- متغيرات البيئة

**للاستيراد:**
1. افتح Postman
2. اضغط Import
3. اسحب الملفين وأفلتهما
4. اختر البيئة "Financial AI Service - Local" من القائمة

### تشغيل الاختبارات الآلية

```bash
cd ai-service

# كل الاختبارات
pytest tests/ -v

# مع تغطية الكود
pytest tests/ -v --cov=app --cov-report=term-missing
```

---

## 11. شرح معمق للأنماط الرئيسية

### لماذا الخط الإنتاجي مقسم لمراحل؟

**السبب الأول: حدود نافذة السياق (Context Window)**
نماذج الذكاء الاصطناعي لديها حد أقصى للنص الذي يمكنها معالجته في مرة واحدة. مستند مالي من 50 صفحة قد يتجاوز هذا الحد. بتقسيم العمل لمراحل، كل مرحلة ترسل فقط البيانات المطلوبة.

**السبب الثاني: تقليل الهلوسة (Hallucination)**
إذا طلبت من النموذج "استخرج كل شيء" في طلب واحد، يزيد احتمال الخطأ. التركيز على مهمة واحدة (مثل "استخرج اسم الشركة والعملة فقط") يعطي نتائج أدق.

**السبب الثالث: إعادة المحاولة المستهدفة**
إذا فشلت المرحلة الثالثة لقائمة الميزانية فقط، نعيد تلك المرحلة فقط -- لا نحتاج لإعادة كل شيء من البداية.

**السبب الرابع: التشخيص**
إذا كانت النتيجة خاطئة، يمكنك فحص مخرجات كل مرحلة لتحديد أين حدث الخطأ بالضبط.

### لماذا استدعاءات LLM مفصولة؟

كل مرحلة في Mapping تستدعي LLM بـ Prompt مختلف ومهمة مختلفة:

| المرحلة | المهمة | المدخلات | المخرجات |
|---------|--------|----------|----------|
| Pass 1 | استخراج البيانات الوصفية | كل النص + الجداول | اسم الشركة، العملة، الفترات |
| Pass 2 | تقسيم المستند | كل النص + نتائج Pass 1 | أي قائمة في أي صفحات |
| Pass 3 | استخراج البنود | جداول القائمة المحددة فقط | بنود مع قيم وهيكل هرمي |
| Pass 4 | استخراج الملاحظات | صفحات الملاحظات فقط | ملاحظات مع مراجع |

كل مرحلة تستفيد من نتائج المراحل السابقة. مثلاً Pass 3 يعرف من Pass 2 أي صفحات تحتوي الميزانية، فيرسل فقط جداول تلك الصفحات لـ LLM.

### لماذا المعالجة المتوازية في Pass 3؟

Pass 3 هو الأكثر كلفة في الوقت. مستند مالي نموذجي يحتوي 4 قوائم:
- ميزانية عمومية (Balance Sheet)
- قائمة الدخل (Income Statement)
- قائمة التدفقات النقدية (Cash Flow)
- قائمة التغيرات في حقوق الملكية (Changes in Equity)

كل واحدة تستغرق 10-15 ثانية مع LLM. بالتتابع: 40-60 ثانية. بالتوازي: 10-15 ثانية.

الشرط: كل استدعاء مستقل -- لا يعتمد على نتائج الآخرين. هذا صحيح لأن كل قائمة لديها جداولها وصفحاتها الخاصة.

### لماذا نحتاج التحقق بعد مخرجات LLM؟

نماذج الذكاء الاصطناعي **غير حتمية** (Non-deterministic). نفس المدخل قد يعطي مخرجات مختلفة:

- مرة: `{"company": {"name_en": "Corp"}, "currency": {"code": "SAR"}}` ✓
- مرة: `{"company_name": "Corp", "currency": "SAR"}` ✗ (أسماء حقول خاطئة)
- مرة: `{"company": null}` ✗ (حقل مطلوب مفقود)

JSON Schema يكتشف هذه المشاكل فوراً ويرمي خطأ واضح بدلاً من ترك بيانات فاسدة تصل لـ Django وتسبب أخطاء غامضة لاحقاً.

### لماذا التصنيف بالكلمات المفتاحية وليس بـ LLM؟

تصنيف البنود المالية (مثل "Cash and cash equivalents" → `CASH_AND_EQUIVALENTS`) يمكن أن يُنفذ بطريقتين:

1. **بالذكاء الاصطناعي** -- نطلب من LLM تصنيف كل بند. المشكلة: غير حتمي، بطيء، مكلف.
2. **بالكلمات المفتاحية** -- جدول يربط المرادفات (مثلاً "نقد"، "cash"، "النقدية") بفئة محددة. المميزات: حتمي 100%، سريع جداً (< 1ms)، مجاني.

في مشروعنا نستخدم الطريقة الثانية. `CategoryMapper` يحمّل ملف CSV يحتوي المرادفات عند بدء التطبيق ويبحث عن تطابقات بخوارزمية "الأطول أولاً" (longest-match-first) -- إذا كان هناك مرادف "cash" ومرادف "cash and cash equivalents"، الأطول يفوز لأنه أكثر تحديداً.

### لماذا الخدمة بدون حالة (Stateless)؟

**Stateful** يعني أن الخدمة تحفظ بيانات بين الطلبات (مثلاً في قاعدة بيانات محلية).
**Stateless** يعني أن كل طلب مستقل تماماً -- الخدمة لا تتذكر شيئاً من الطلب السابق.

اخترنا Stateless لأن:
1. **Django يدير الحالة** -- `PipelineRun` و `StageExecution` في Django يتتبعان تقدم المعالجة. تكرار هذا في الخدمة المصغرة يخلق "دماغين" (Split brain) يمكن أن يتعارضا.
2. **التوسع أسهل** -- يمكنك تشغيل 10 نسخ من الخدمة خلف موازن أحمال (Load balancer) بدون قلق بشأن مزامنة البيانات.
3. **البساطة** -- لا حاجة لقاعدة بيانات أو Redis أو إدارة جلسات.

---

## ملخص

هذا المشروع مثال عملي على كيفية بناء خدمة مصغرة إنتاجية تتعامل مع الذكاء الاصطناعي. الأفكار الرئيسية:

1. **افصل ما يتغير عن ما لا يتغير** -- الواجهات المجردة تسمح بتبديل التطبيقات.
2. **الخدمة المصغرة = مسؤولية واحدة** -- هذه الخدمة تعالج الذكاء الاصطناعي فقط.
3. **التحقق في كل مرحلة** -- لا تثق في مخرجات LLM بدون تحقق.
4. **السجلات المنظمة + معرّف الطلب** -- أساسيات لتشخيص المشاكل في الإنتاج.
5. **الاختبارات بكائنات وهمية** -- لا تعتمد على خدمات خارجية في الاختبارات.
6. **Docker للنشر** -- ضمان أن البيئة متطابقة في التطوير والإنتاج.
