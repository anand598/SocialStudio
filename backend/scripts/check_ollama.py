"""Optional real local inference check. Does not fall back to demo copy."""
import argparse
import json
from pathlib import Path
from app.services.ai.provider import OllamaProvider


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path, default=Path(__file__).resolve().parents[2] / "assets/sample-product.png")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    provider = OllamaProvider()
    analysis = provider.analyze_product_image(str(args.image.resolve()))
    content = provider.generate_social_content(analysis, {"brand_name": "Studio Sample", "call_to_action": "Explore the collection"})
    result = {"generation_mode": "ollama", "analysis": analysis.model_dump(), "content": content.model_dump()}
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")
    else:
        print(text)


if __name__ == "__main__":
    main()
