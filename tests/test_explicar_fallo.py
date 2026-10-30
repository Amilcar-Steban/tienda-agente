import boto3
from botocore.stub import ANY, Stubber

from scripts.explicar_fallo import explicar


def test_redacta_el_log_y_pide_temperatura_cero():
    cliente = boto3.client("bedrock-runtime", region_name="us-east-1",
                           aws_access_key_id="x", aws_secret_access_key="x")
    respuesta = {"output": {"message": {"role": "assistant", "content": [{"text": "**Causa probable:** un test"}]}},
                 "usage": {"inputTokens": 50, "outputTokens": 10, "totalTokens": 60},
                 "stopReason": "end_turn", "metrics": {"latencyMs": 1}}
    with Stubber(cliente) as s:
        s.add_response("converse", respuesta, {
            "modelId": "modelo-prueba", "system": ANY,
            "messages": [{"role": "user", "content": [{"text": "<log>\nFAILED test_pedidos\nDB_PASSWORD=[REDACTADO]\n</log>"}]}],
            "inferenceConfig": {"maxTokens": 400, "temperature": 0}})
        salida = explicar("FAILED test_pedidos\nDB_PASSWORD=hunter22", cliente, "modelo-prueba")
    assert "Causa probable" in salida and "50+10 tokens" in salida
