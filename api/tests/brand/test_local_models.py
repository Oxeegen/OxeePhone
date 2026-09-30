"""OxeePhone lot 3: Local Models configuration, model listing, embeddings and
local document processing."""

import json

import httpx
import pytest

from api.brand import documents, embeddings, local_models
from api.schemas.ai_model_configuration import OrganizationAIModelConfigurationV2
from api.services.configuration.registry import (
    REGISTRY,
    ServiceType,
    SpeachesEmbeddingsConfiguration,
)


def _schemas(service_type: ServiceType) -> dict[str, dict]:
    return {
        provider: cls.model_json_schema()
        for provider, cls in REGISTRY[service_type].items()
    }


# ------------------------------------------------------------ configuration


@pytest.mark.parametrize(
    "service_type",
    [ServiceType.LLM, ServiceType.TTS, ServiceType.STT, ServiceType.EMBEDDINGS],
)
def test_only_local_models_are_offered(service_type):
    restricted = local_models.restrict_provider_schemas(
        service_type, _schemas(service_type)
    )
    assert list(restricted) == ["speaches"]
    schema = restricted["speaches"]
    assert schema["title"] == "Local Models"
    assert "provider_docs_url" not in schema
    assert schema["properties"]["base_url"]["default"] == ""
    assert schema["properties"]["model"]["default"] == ""
    assert "examples" not in schema["properties"]["model"]


def test_realtime_is_not_offered_and_stt_defaults_to_french():
    assert (
        local_models.restrict_provider_schemas(
            ServiceType.REALTIME, _schemas(ServiceType.REALTIME)
        )
        == {}
    )
    stt = local_models.restrict_provider_schemas(
        ServiceType.STT, _schemas(ServiceType.STT)
    )
    assert stt["speaches"]["properties"]["language"]["default"] == "fr"


def _pipeline(**providers):
    services = {
        "llm": {"provider": "speaches", "model": "m", "base_url": "http://x/v1"},
        "tts": {"provider": "speaches", "model": "t", "base_url": "http://x/v1"},
        "stt": {"provider": "speaches", "model": "s", "base_url": "http://x/v1"},
    }
    for service, provider in providers.items():
        services[service] = {
            "provider": provider,
            "model": "gpt-4.1",
            "api_key": "sk-test",
        }
    return OrganizationAIModelConfigurationV2.model_validate(
        {"version": 2, "mode": "byok", "byok": {"mode": "pipeline", "pipeline": services}}
    )


def test_local_models_pipeline_is_accepted():
    local_models.enforce_local_models(_pipeline())


def test_third_party_provider_is_rejected():
    with pytest.raises(ValueError) as exc:
        local_models.enforce_local_models(_pipeline(llm="openai"))
    assert exc.value.args[0] == [
        {"model": "llm", "message": "Only Local Models can be used."}
    ]


def test_dograh_managed_mode_is_rejected():
    configuration = OrganizationAIModelConfigurationV2.model_validate(
        {"version": 2, "mode": "dograh", "dograh": {"api_key": "key"}}
    )
    with pytest.raises(ValueError):
        local_models.enforce_local_models(configuration)


def test_masked_key_is_resolved_from_stored_configuration():
    stored = OrganizationAIModelConfigurationV2.model_validate(
        {
            "version": 2,
            "mode": "byok",
            "byok": {
                "mode": "pipeline",
                "pipeline": {
                    "llm": {
                        "provider": "speaches",
                        "model": "m",
                        "base_url": "http://x/v1",
                        "api_key": "secret-abcd",
                    },
                    "tts": {"provider": "speaches", "model": "t", "base_url": "http://x"},
                    "stt": {"provider": "speaches", "model": "s", "base_url": "http://x"},
                },
            },
        }
    )
    assert local_models.resolve_api_key("*******abcd", stored, "llm") == "secret-abcd"
    assert local_models.resolve_api_key("*******zzzz", stored, "llm") is None
    assert local_models.resolve_api_key("plain", stored, "llm") == "plain"
    assert local_models.resolve_api_key("", stored, "llm") is None


# ------------------------------------------------------------ model listing


@pytest.fixture
def mock_http(monkeypatch):
    """Route every httpx.AsyncClient created by the brand module to a handler."""
    state = {"handler": None, "requests": []}
    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        def handle(request):
            state["requests"].append(request)
            return state["handler"](request)

        kwargs["transport"] = httpx.MockTransport(handle)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(local_models.httpx, "AsyncClient", factory)
    return state


async def test_lists_models_from_openai_compatible_endpoint(mock_http):
    mock_http["handler"] = lambda request: httpx.Response(
        200, json={"object": "list", "data": [{"id": "b-model"}, {"id": "a-model"}]}
    )
    models = await local_models.list_endpoint_models("http://vllm:8000/v1/", "key")
    assert models == ["a-model", "b-model"]
    request = mock_http["requests"][0]
    assert str(request.url) == "http://vllm:8000/v1/models"
    assert request.headers["Authorization"] == "Bearer key"


async def test_listing_without_key_sends_no_authorization(mock_http):
    mock_http["handler"] = lambda request: httpx.Response(200, json={"data": []})
    await local_models.list_endpoint_models("http://vllm/v1", None)
    assert "Authorization" not in mock_http["requests"][0].headers


@pytest.mark.parametrize(
    "response, message",
    [
        (httpx.Response(401), "rejected the API key"),
        (httpx.Response(404), "HTTP 404"),
        (httpx.Response(200, text="<html>"), "did not return JSON"),
    ],
)
async def test_listing_errors_are_user_facing(mock_http, response, message):
    mock_http["handler"] = lambda request: response
    with pytest.raises(local_models.LocalModelsError, match=message):
        await local_models.list_endpoint_models("http://vllm/v1", None)


async def test_listing_requires_a_base_url():
    with pytest.raises(local_models.LocalModelsError, match="base URL"):
        await local_models.list_endpoint_models("  ", None)


# ------------------------------------------------------------ transcription


async def test_recording_transcription_uses_organization_stt(mock_http, monkeypatch):
    from api.schemas.ai_model_configuration import EffectiveAIModelConfiguration
    from api.services.configuration import ai_model_configuration

    effective = EffectiveAIModelConfiguration.model_validate(
        {
            "stt": {
                "provider": "speaches",
                "model": "whisper-large-v3",
                "base_url": "http://stt/v1",
                "api_key": "k",
            }
        }
    )

    class Resolved:
        pass

    resolved = Resolved()
    resolved.effective = effective

    async def fake_resolved(**_kwargs):
        return resolved

    monkeypatch.setattr(
        ai_model_configuration, "get_resolved_ai_model_configuration", fake_resolved
    )
    mock_http["handler"] = lambda request: httpx.Response(200, json={"text": " Bonjour "})

    result = await local_models.transcribe_with_organization_stt(
        organization_id=1,
        audio_data=b"RIFF",
        filename="a.wav",
        content_type="audio/wav",
        language="fr",
    )
    assert result == {"transcript": "Bonjour"}
    request = mock_http["requests"][0]
    assert str(request.url) == "http://stt/v1/audio/transcriptions"
    body = request.content.decode(errors="ignore")
    assert "whisper-large-v3" in body and 'name="language"' in body


# ------------------------------------------------------------ embeddings


def test_short_vectors_are_zero_padded_and_keep_cosine():
    vector = [0.6, 0.8]
    padded = embeddings.pad_embedding(vector, "m")
    assert len(padded) == 1536
    assert padded[:2] == vector and not any(padded[2:])


def test_oversized_vectors_are_rejected():
    with pytest.raises(embeddings.EmbeddingDimensionTooLargeError, match="4096"):
        embeddings.pad_embedding([0.0] * 4096, "big-model")


def test_speaches_embeddings_config_needs_no_key():
    config = SpeachesEmbeddingsConfiguration(model="bge-m3", base_url="http://e/v1")
    assert config.api_key is None


async def test_factory_builds_local_embedding_service():
    from api.services.gen_ai import build_embedding_service

    service = await build_embedding_service(
        db_client=None,
        provider="speaches",
        api_key=None,
        model="bge-m3",
        base_url="http://e/v1",
    )
    assert isinstance(service, embeddings.LocalEmbeddingService)
    assert service.get_model_id() == "bge-m3"


# ------------------------------------------------------------ documents


def test_markdown_is_chunked_with_heading_context(tmp_path):
    path = tmp_path / "guide.md"
    path.write_text(
        "# Accueil\n\nBonjour et bienvenue.\n\n## Horaires\n\nOuvert du lundi au vendredi.\n"
    )
    result = documents.process_document_locally(
        file_path=str(path), filename="guide.md", retrieval_mode="chunked", max_tokens=128
    )
    chunks = result["chunks"]
    assert [c["chunk_text"] for c in chunks] == [
        "Bonjour et bienvenue.",
        "Ouvert du lundi au vendredi.",
    ]
    assert chunks[1]["contextualized_text"] == (
        "Accueil > Horaires\nOuvert du lundi au vendredi."
    )
    assert [c["chunk_index"] for c in chunks] == [0, 1]
    assert result["docling_metadata"]["processor"] == "oxeephone-local"


def test_long_text_is_split_under_the_token_budget(tmp_path):
    path = tmp_path / "long.txt"
    sentence = "Ceci est une phrase de test assez longue pour remplir un morceau. "
    path.write_text(sentence * 100)
    result = documents.process_document_locally(
        file_path=str(path), filename="long.txt", retrieval_mode="chunked", max_tokens=32
    )
    assert len(result["chunks"]) > 1
    assert all(
        len(c["chunk_text"]) <= 32 * documents.CHARS_PER_TOKEN for c in result["chunks"]
    )


def test_txt_keeps_hash_lines_as_text(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("# pas un titre\nligne suivante\n")
    result = documents.process_document_locally(
        file_path=str(path), filename="notes.txt", retrieval_mode="chunked", max_tokens=128
    )
    assert result["chunks"][0]["chunk_text"] == "# pas un titre\nligne suivante"


def test_docx_headings_and_tables(tmp_path):
    import docx

    document = docx.Document()
    document.add_heading("Tarifs", level=1)
    document.add_paragraph("Consultation standard.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "Acte", "Prix"
    table.cell(1, 0).text, table.cell(1, 1).text = "Visite", "30 €"
    path = tmp_path / "tarifs.docx"
    document.save(path)

    result = documents.process_document_locally(
        file_path=str(path), filename="tarifs.docx", retrieval_mode="chunked", max_tokens=128
    )
    text = result["chunks"][0]["contextualized_text"]
    assert text.startswith("Tarifs\n")
    assert "Consultation standard." in text and "Visite | 30 €" in text


def test_pdf_text_is_extracted(tmp_path):
    from pypdf import PdfWriter
    from pypdf.generic import (
        DecodedStreamObject,
        DictionaryObject,
        NameObject,
    )

    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 100 Td (Horaires du cabinet) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    path = tmp_path / "doc.pdf"
    with open(path, "wb") as f:
        writer.write(f)

    result = documents.process_document_locally(
        file_path=str(path), filename="doc.pdf", retrieval_mode="chunked", max_tokens=128
    )
    assert result["chunks"][0]["chunk_text"] == "Horaires du cabinet"
    assert result["chunks"][0]["chunk_metadata"]["pages"] == [1]


def test_scanned_pdf_gets_a_clear_error(tmp_path):
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    path = tmp_path / "scan.pdf"
    with open(path, "wb") as f:
        writer.write(f)
    with pytest.raises(documents.DocumentProcessingError, match="scanned"):
        documents.process_document_locally(
            file_path=str(path), filename="scan.pdf", retrieval_mode="chunked", max_tokens=128
        )


@pytest.mark.parametrize("name, message", [("old.doc", ".docx"), ("x.xlsx", "Unsupported")])
def test_unsupported_formats_get_a_clear_error(tmp_path, name, message):
    path = tmp_path / name
    path.write_bytes(b"data")
    with pytest.raises(documents.DocumentProcessingError, match=message):
        documents.process_document_locally(
            file_path=str(path), filename=name, retrieval_mode="chunked", max_tokens=128
        )


def test_full_document_mode_returns_text_only(tmp_path):
    path = tmp_path / "faq.json"
    path.write_text(json.dumps({"question": "Horaires ?", "reponse": "9h-18h"}))
    result = documents.process_document_locally(
        file_path=str(path), filename="faq.json", retrieval_mode="full_document", max_tokens=128
    )
    assert result["chunks"] == []
    assert '"reponse": "9h-18h"' in result["full_text"]


# ------------------------------------------------------------ voice


def test_voice_tab_defaults_and_speed_range():
    tts = local_models.restrict_provider_schemas(
        ServiceType.TTS, _schemas(ServiceType.TTS)
    )["speaches"]["properties"]
    assert tts["voice"]["default"] == "fr_cedric"
    assert tts["language"]["default"] == "fr"
    assert "fr" in tts["language"]["examples"]
    assert (tts["speed"]["minimum"], tts["speed"]["maximum"]) == (0.5, 2.0)


def _tts_service(**kwargs):
    from pipecat.services.speaches.tts import SpeachesTTSSettings

    from api.brand.tts import LocalModelsTTSService

    return LocalModelsTTSService(
        base_url="http://tts/v1",
        settings=SpeachesTTSSettings(model="voxee-tts-pro", voice="fr_cedric", speed=1.2),
        **kwargs,
    )


def test_tts_forwards_language_hint():
    params = _tts_service(language="fr").speech_params("Bonjour")
    assert params == {
        "input": "Bonjour",
        "model": "voxee-tts-pro",
        "voice": "fr_cedric",
        "response_format": "pcm",
        "speed": 1.2,
        "extra_body": {"language": "fr"},
    }


def test_tts_without_language_sends_no_extra_body():
    assert "extra_body" not in _tts_service(language="  ").speech_params("x")


async def test_voice_preview_matches_call_rendering(mock_http):
    import io
    import wave

    pcm = (1000).to_bytes(2, "little", signed=True) * 4
    mock_http["handler"] = lambda request: httpx.Response(
        200, content=pcm + b"\x01", headers={"content-type": "audio/pcm"}
    )
    audio = await local_models.synthesize_preview(
        base_url="http://tts/v1/",
        api_key="k",
        model="voxee-tts-pro",
        voice="fr_cedric",
        speed=1.1,
        language="fr",
        text="Chez Oxeegen, RDV à 14h30.",
        volume_gain_db=6.0,
        pronunciations="Oxeegen = Oxy-jène",
    )
    request = mock_http["requests"][0]
    assert str(request.url) == "http://tts/v1/audio/speech"
    assert json.loads(request.content) == {
        "model": "voxee-tts-pro",
        "voice": "fr_cedric",
        "input": "Chez Oxy-jène, rendez-vous à quatorze heures trente.",
        "response_format": "pcm",
        "speed": 1.1,
        "language": "fr",
    }
    with wave.open(io.BytesIO(audio)) as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (24000, 1, 2)
        frames = wav.readframes(wav.getnframes())
    # Odd trailing byte dropped, +6 dB ~ x1.995.
    assert len(frames) == 8
    assert int.from_bytes(frames[:2], "little", signed=True) == 1995


async def test_voice_preview_surfaces_endpoint_errors(mock_http):
    mock_http["handler"] = lambda request: httpx.Response(
        400, json={"detail": "unknown voice 'x'. See GET /v1/audio/voices"}
    )
    with pytest.raises(local_models.LocalModelsError, match="unknown voice 'x'"):
        await local_models.synthesize_preview(
            base_url="http://tts/v1", api_key=None, model="m", voice="x",
            speed=None, language=None, text="t",
        )


# ------------------------------------------------------------ speech text


@pytest.mark.parametrize(
    "n, words",
    [
        (0, "zéro"), (21, "vingt et un"), (71, "soixante et onze"), (80, "quatre-vingts"),
        (81, "quatre-vingt-un"), (91, "quatre-vingt-onze"), (200, "deux cents"),
        (201, "deux cent un"), (1000, "mille"), (2026, "deux mille vingt-six"),
        (80000, "quatre-vingt mille"), (1000000, "un million"), (2000000, "deux millions"),
    ],
)
def test_french_numbers(n, words):
    from api.brand.speech_text import number_to_words

    assert number_to_words(n) == words


@pytest.mark.parametrize(
    "text, spoken",
    [
        ("RDV à 14h30", "rendez-vous à quatorze heures trente"),
        ("de 9h05 à 21h", "de neuf heures cinq à vingt et une heures"),
        ("à 12h ou 0h", "à midi ou minuit"),
        ("à 18:30", "à dix-huit heures trente"),
        ("au 06 12 34 56 78", "au zéro six, douze, trente-quatre, cinquante-six, soixante-dix-huit"),
        ("au 01.45.67.89.00", "au zéro un, quarante-cinq, soixante-sept, quatre-vingt-neuf, zéro zéro"),
        ("45,50 €", "quarante-cinq euros cinquante"),
        ("1 250 euros", "mille deux cent cinquante euros"),
        ("1 €", "un euro"),
        ("15 %", "quinze pour cent"),
        ("le 12/03/2026", "le douze mars deux mille vingt-six"),
        ("le 1/04", "le premier avril"),
        ("le 1er, la 1re, le 2e, le 21ème", "le premier, la première, le deuxième, le vingt et unième"),
        ("Dr Martin, Mme Durand, M. Dupont", "docteur Martin, madame Durand, monsieur Dupont"),
        ("n° 42, merci", "numéro quarante-deux, merci"),
        ("3,14 km", "trois virgule quatorze km"),
        ("dossier A123, code 75011", "dossier A123, code 75011"),
    ],
)
def test_french_normalization(text, spoken):
    from api.brand.speech_text import normalize_french

    assert normalize_french(text) == spoken


def test_pronunciations_override_and_other_languages_untouched():
    from api.brand.speech_text import parse_pronunciations, prepare_speech_text

    entries = parse_pronunciations("# comment\nDr Martin => docteur Martaine\nvLLM = vé elle elle aime\n\nbad line")
    assert entries == [("Dr Martin", "docteur Martaine"), ("vLLM", "vé elle elle aime")]
    assert (
        prepare_speech_text("dr martin utilise VLLM à 9h", language="fr", pronunciations=entries)
        == "docteur Martaine utilise vé elle elle aime à neuf heures"
    )
    assert prepare_speech_text("Meet at 9h, 2 people.", language="en") == "Meet at 9h, 2 people."


def test_gain_scales_and_clips():
    from api.brand.tts import apply_gain, gain_factor

    pcm = b"".join(v.to_bytes(2, "little", signed=True) for v in (1000, -1000, 30000))
    out = apply_gain(pcm, gain_factor(6.0))
    values = [int.from_bytes(out[i : i + 2], "little", signed=True) for i in range(0, 6, 2)]
    assert values == [1995, -1995, 32767]
    assert apply_gain(pcm, gain_factor(0)) is pcm


def test_tts_service_prepares_text_for_synthesis_only():
    service = _tts_service(language="fr", pronunciations="Oxeegen = Oxy-jène", volume_gain_db=3)
    assert service.speech_params("Oxeegen vous rappelle à 9h")["input"] == (
        "Oxy-jène vous rappelle à neuf heures"
    )
