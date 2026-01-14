[![CI](https://img.shields.io/github/actions/workflow/status/bieniu/ha-perplexity/ci.yml?branch=master&label=CI&logo=github&style=popout)](https://github.com/bieniu/ha-perplexity/actions/workflows/ci.yml?query=branch%3Amaster)
[![Validate with hassfest](https://github.com/bieniu/ha-perplexity/actions/workflows/hassfest.yml/badge.svg)](https://github.com/bieniu/ha-perplexity/actions/workflows/hassfest.yml)
[![GitHub Release][releases-shield]][releases]
[![GitHub All Releases][downloads-total-shield]][releases]
[![Buy me a coffee][buy-me-a-coffee-shield]][buy-me-a-coffee]
[![PayPal_Me][paypal-me-shield]][paypal-me]
[![Revolut.Me][revolut-me-shield]][revolut-me]

# Perplexity
Perplexity integration for Home Assistant.

<img width="1044" height="585" alt="obraz" src="https://github.com/user-attachments/assets/67a37ebb-6726-490a-a91f-82e14d997abc" />

## Installation

You can install this integration manually or via [HACS](https://hacs.xyz) if you add the repository to the custom repository list (**three dot menu** >> **Custom repositories**)

## Configuration

To configure integration in Home Assistant, go to **Settings** >> **Devices & services** >> **Add integration** >> **Perplexity** or use My Home Assistant link.

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=perplexity)

To generate API key go to [https://www.perplexity.ai/account/api/keys](https://www.perplexity.ai/account/api/keys)

## Features
Perplexity integration supports:

- [AI Task](https://www.home-assistant.io/integrations/ai_task/) platform
- **Sonar**, **Sonar Pro** and **Sonar Reasoning Pro** models
- **reasoning effort** configuration (for models supporting reasoning)
- controlling **web search** option

## Examples

### Generating a short description of weather conditions

```yaml
action: ai_task.generate_data
data:
  task_name: Weather Description
  entity_id: ai_task.sonar
  instructions: >-
    Based on this {{ states.weather.home }} and an image create short weather
    description (ONLY ONE SENTENCE).
```

Response:

```
The sky is overcast with dark, ragged clouds on this chilly January morning, threatening rain and a brisk wind.
```

### Counting objects from a camera snapshot

```yaml
action: ai_task.generate_data
data:
  task_name: Number of cars
  entity_id: ai_task.sonar
  instructions: In the attached photo, count the cars in the parking lot.
  attachments:
    media_content_id: media-source://camera/camera.parking
    media_content_type: application/vnd.apple.mpegurl
    metadata:
      title: parking
      thumbnail: /api/camera_proxy/camera.parking
      media_class: video
      navigateIds:
        - media_content_type: app
          media_content_id: media-source://camera
  structure:
    car_count:
      required: true
      selector:
        number:
```

Response:

```yaml
data:
  car_count: 42
```

## How to debug

To debug the integration add this to your `logger` configuration:

```yaml
# configuration.yaml file
logger:
  default: warning
  logs:
    custom_components.perplexity: debug
    perplexity: debug
```

## How to create a dev environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
prek install
```

[releases]: https://github.com/bieniu/ha-perplexity/releases
[releases-shield]: https://img.shields.io/github/release/bieniu/ha-perplexity.svg?style=popout
[downloads-total-shield]: https://img.shields.io/github/downloads/bieniu/ha-perplexity/total
[buy-me-a-coffee-shield]: https://img.shields.io/static/v1.svg?label=%20&message=Buy%20me%20a%20coffee&color=6f4e37&logo=buy%20me%20a%20coffee&logoColor=white
[buy-me-a-coffee]: https://www.buymeacoffee.com/QnLdxeaqO
[paypal-me-shield]: https://img.shields.io/static/v1.svg?label=%20&message=PayPal.Me&logo=paypal
[paypal-me]: https://www.paypal.me/bieniu79
[revolut-me]: https://revolut.me/maciejbieniek
[revolut-me-shield]: https://img.shields.io/static/v1.svg?label=%20&message=Revolut&logo=revolut
