"""Provider adapters return the same validated classification result format."""
import json
from .ai_settings import AIConfig, get_api_key
from .config import AI_INSTRUCTIONS

OLLAMA_HOST = 'http://127.0.0.1:11434'


class LocalModelRequired(RuntimeError):
    pass


def ensure_local_model(model):
    import httpx
    # Inspect raw metadata: older Ollama Python clients omit remote_host fields.
    with httpx.Client(base_url=OLLAMA_HOST, timeout=10, trust_env=False) as client:
        response = client.post('/api/show', json={'model': model})
        response.raise_for_status()
        metadata = response.json()
    if (metadata.get('remote_host') or metadata.get('remote_model')
            or not isinstance(metadata.get('model_info'), dict)
            or not metadata['model_info'].get('general.architecture')):
        raise LocalModelRequired('This model is remote or cannot be verified as local. Choose a downloaded local model in AI settings.')


def ollama_client(timeout=180):
    import ollama
    return ollama.Client(host=OLLAMA_HOST, timeout=timeout, trust_env=False)


def classify(payload, result_type, categories, config, api_key=None):
    messages = [
        {'role': 'system', 'content': AI_INSTRUCTIONS + '\nAllowed categories: ' + ', '.join(categories)},
        {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
    ]
    if config.provider == 'rules':
        raise RuntimeError('AI is disabled. Open AI settings to configure a provider.')
    if config.provider == 'ollama':
        ensure_local_model(config.model)
        response = ollama_client().chat(model=config.model, messages=messages,
            format=result_type.model_json_schema(), options={'temperature': 0})
        return result_type.model_validate_json(response.message.content)
    from openai import OpenAI
    # Fixed official endpoint; environment variables cannot redirect documents.
    with OpenAI(api_key=api_key or get_api_key(), base_url='https://api.openai.com/v1',
                timeout=120, max_retries=0) as client:
        response = client.responses.parse(model=config.model, input=messages,
            text_format=result_type, store=False, max_output_tokens=4096)
    if response.output_parsed is None:
        raise RuntimeError('OpenAI returned no usable structured result (possibly a refusal or output limit).')
    return response.output_parsed


def error_message(exc, config):
    if config.provider == 'ollama':
        if isinstance(exc, LocalModelRequired):
            return str(exc)
        import httpx
        import ollama
        if isinstance(exc, (httpx.ConnectError, ConnectionError)):
            return 'Cannot connect to local Ollama. Open AI settings to start or install it.'
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
            return f'Model {config.model} is unavailable. Open AI settings to download or select a model.'
        if isinstance(exc, ollama.ResponseError) and exc.status_code == 404:
            return f'Model {config.model} is unavailable. Open AI settings to download or select a model.'
        return 'Local AI could not complete the request. Check Ollama, model availability and memory, then retry.'
    if config.provider == 'openai':
        if isinstance(exc, RuntimeError) and str(exc).startswith('No OpenAI API key is saved'):
            return 'No API key is saved. Enter your key in AI settings and test the connection.'
        if isinstance(exc, ImportError):
            return 'OpenAI support is missing. Install the application requirements and retry.'
        from openai import AuthenticationError, PermissionDeniedError, RateLimitError, NotFoundError
        if isinstance(exc, AuthenticationError):
            return 'OpenAI rejected the API key. Update it in AI settings.'
        if isinstance(exc, PermissionDeniedError):
            return 'The OpenAI key does not have permission for this model.'
        if isinstance(exc, RateLimitError):
            return 'OpenAI usage limits or available credits were reached. Check your API account.'
        if isinstance(exc, NotFoundError):
            return 'The selected OpenAI model is unavailable. Choose a model your API account can access.'
        # Do not show raw remote errors: they can contain submitted document text.
        return 'OpenAI could not complete the request. Check connectivity, model access and API account billing.'
    return 'AI is disabled. Python rules are still available.'
