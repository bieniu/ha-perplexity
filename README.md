[![Validate with hassfest](https://github.com/bieniu/ha-perplexity/actions/workflows/hassfest.yml/badge.svg)](https://github.com/bieniu/ha-perplexity/actions/workflows/hassfest.yml)
[![GitHub Release][releases-shield]][releases]
[![GitHub All Releases][downloads-total-shield]][releases]
[![Buy me a coffee][buy-me-a-coffee-shield]][buy-me-a-coffee]
[![PayPal_Me][paypal-me-shield]][paypal-me]
[![Revolut.Me][revolut-me-shield]][revolut-me]

# Perplexity
Perplexity integration for Home Assistant.

## Installation

You can install this integration manually or via [HACS](https://hacs.xyz) if you add the repository to the custom repository list (**three dot menu** >> **Custom repositories**)

## Configuration

To configure integration in Home Assistant, go to **Settings** >> **Devices & services** >> **Add integration** >> **Perplexity** or use My Home Assistant link.

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=perplexity)

To generate API key go to [https://www.perplexity.ai/account/api/keys](https://www.perplexity.ai/account/api/keys)

## How to debug

To debug the integration add this to your `logger` configuration:

```yaml
# configuration.yaml file
logger:
  default: warning
  logs:
    custom_components.perplexity: debug
```

## How to create dev environment

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
