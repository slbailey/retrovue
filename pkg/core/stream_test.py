import asyncio
import logging
from pathlib import Path

from retrovue.adapters.renderers.ffmpeg_ts_renderer import FFmpegTSRenderer
from retrovue.adapters.producers.test_pattern_producer import TestPatternProducer
from retrovue.adapters.producers.file_producer import FileProducer

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")


async def stream_to_tcp(host: str = "127.0.0.1", port: int = 1234) -> None:
    renderer = FFmpegTSRenderer(output_url=f"tcp://{host}:{port}?listen")

    test_pattern = TestPatternProducer()
    cheers_path = Path(
        r"R:\media\tv\Cheers (1982) {imdb-tt0083399}\Season 01\Cheers (1982) - S01E03 - The Tortelli Tort [Bluray-720p][AAC 2.0][x264]-Bordure.mp4"
    )

    if not cheers_path.exists():
        logging.warning("Sample file %s does not exist; demo will stay on test pattern.", cheers_path)

    file_producer = FileProducer(file_path=str(cheers_path))

    producers = [
        ("Test Pattern", test_pattern),
        ("Cheers Episode", file_producer),
    ]

    index = 0

    try:
        while True:
            name, producer = producers[index]
            try:
                logging.info("Switching to %s", name)
                renderer.switch_source(producer)
            except Exception as exc:
                logging.error("Failed to switch to %s: %s", name, exc)
                logging.info("Falling back to Test Pattern")
                renderer.switch_source(test_pattern)
                index = 1  # next attempt will retry the file producer
                await asyncio.sleep(5)
                continue

            index = (index + 1) % len(producers)
            await asyncio.sleep(10)
    except asyncio.CancelledError:
        raise
    except KeyboardInterrupt:
        logging.info("Stopping stream...")
    finally:
        renderer.stop()


if __name__ == "__main__":
    asyncio.run(stream_to_tcp())

