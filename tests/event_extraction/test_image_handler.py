"""
Тесты для обработчика изображений.
"""

import pytest
from pathlib import Path

from src.event_extraction.image_handler import ImageHandler


def test_image_handler_init():
    """Тест инициализации ImageHandler."""
    handler = ImageHandler(
        images_dir="test_images",
        image_llm_base_url="https://api.test.com/v1",
        image_llm_api_keys=["key1", "key2"],
        image_llm_model="dall-e-3"
    )
    
    assert handler.image_llm_model == "dall-e-3"
    assert len(handler.image_llm_api_keys) == 2
    assert handler.images_dir == Path("test_images")


def test_rotate_image_key():
    """Тест ротации API ключей."""
    handler = ImageHandler(
        image_llm_api_keys=["key1", "key2", "key3"]
    )
    
    assert handler._current_image_key_idx == 0
    
    handler._rotate_image_key()
    assert handler._current_image_key_idx == 1
    
    handler._rotate_image_key()
    assert handler._current_image_key_idx == 2
    
    handler._rotate_image_key()
    assert handler._current_image_key_idx == 0  # Циклический переход


def test_rotate_single_key():
    """Тест ротации с одним ключом."""
    handler = ImageHandler(
        image_llm_api_keys=["key1"]
    )
    
    # Ротация не должна работать с одним ключом
    result = handler._rotate_image_key()
    assert not result
    assert handler._current_image_key_idx == 0


@pytest.mark.asyncio
async def test_generate_image_no_config():
    """Тест генерации без настроек."""
    handler = ImageHandler()  # Без настроек
    
    result = await handler.generate_image("Test prompt")
    assert result is None


@pytest.mark.asyncio
async def test_download_image_invalid_url():
    """Тест скачивания по невалидному URL."""
    handler = ImageHandler(images_dir="test_images")
    
    result = await handler.download_image_from_url("http://invalid-url-12345.com/image.jpg")
    assert result is None


def test_image_to_base64_nonexistent():
    """Тест конвертации несуществующего файла."""
    handler = ImageHandler(images_dir="test_images")
    
    result = handler.image_to_base64("nonexistent_file.jpg")
    assert result is None
