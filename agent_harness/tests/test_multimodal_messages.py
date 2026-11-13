import base64

from agent_harness.core.messages import HumanMessage, ImageContent, from_jsonable, to_jsonable
from agent_harness.core.models import _to_anthropic, _to_openai


def test_image_message_serialization_and_openai_conversion():
    image = ImageContent(
        data=base64.b64encode(b"fake-png").decode("ascii"),
        media_type="image/png",
        label="source page 1",
    )
    message = HumanMessage(content="Inspect this page", images=[image])

    restored = from_jsonable(to_jsonable(message))
    assert restored == message

    converted = _to_openai([message])[0]
    assert converted["content"][1]["text"] == "[image: source page 1]"
    assert converted["content"][2]["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )


def test_anthropic_conversion_uses_inline_base64():
    image = ImageContent(data="YWJj", media_type="image/jpeg", label="candidate")
    _, converted = _to_anthropic([HumanMessage(content="Review", images=[image])])
    source = converted[0]["content"][2]["source"]
    assert source == {"type": "base64", "media_type": "image/jpeg", "data": "YWJj"}
