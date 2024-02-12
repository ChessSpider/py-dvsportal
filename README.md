# DVSPortal

Asynchronous Python client for the DVSPortal API. This library provides an easy-to-use async interface to interact with the DVSPortal API, allowing for operations such as fetching balances, creating reservations, and managing license plates.

## Installation

To install DVSPortal, run the following command in your terminal:

```bash
pip install dvsportal
```

Ensure you are using Python 3.9 or newer, as this library utilizes modern Python features and type hinting.

## Requirements

- Python 3.9+
- aiohttp
- async_timeout
- yarl

These dependencies will be automatically installed when you install the DVSPortal package.

## Quick Start

Here's a quick example to get you started:

```python
import asyncio
from dvsportal import DVSPortal

async def main():
    async with DVSPortal(api_host='api.example.com', identifier='your_identifier', password='your_password') as portal:
        await portal.update()
        print(f"Balance: {portal.balance}")
        print(f"Unit Price: {portal.unit_price}")
        print(f"Active Reservations: {portal.active_reservations}")

if __name__ == '__main__':
    asyncio.run(main())
```

Replace `'api.example.com'`, `'your_identifier'`, and `'your_password'` with your actual DVSPortal API host and credentials.

## Examples

### Creating a Reservation

To create a reservation for a license plate:

```python
import asyncio
from dvsportal import DVSPortal
from datetime import datetime, timedelta

async def create_reservation():
    async with DVSPortal(api_host='api.example.com', identifier='your_identifier', password='your_password') as portal:
        await portal.create_reservation(
            license_plate_value='ABC123',
            date_from=datetime.now(),
            date_until=datetime.now() + timedelta(days=1)
        )
        print("Reservation created successfully.")

if __name__ == '__main__':
    asyncio.run(create_reservation())
```

### Managing License Plates

To add a new license plate:

```python
import asyncio
from dvsportal import DVSPortal

async def add_license_plate():
    async with DVSPortal(api_host='api.example.com', identifier='your_identifier', password='your_password') as portal:
        await portal.store_license_plate(
            license_plate='ABC123',
            name='My Car'
        )
        print("License plate added successfully.")

if __name__ == '__main__':
    asyncio.run(add_license_plate())
```

## Features

- Asynchronous API communication
- Fetching account balance and unit prices
- Managing reservations
- Handling license plates

## How to Contribute

1. Fork the repository on GitHub.
2. Clone your forked repository to your local machine.
3. Create a new branch for your feature or bug fix.
4. Implement your changes.
5. Run tests to ensure your changes don't break existing functionality.
6. Commit your changes with a clear commit message.
7. Push your changes to your fork on GitHub.
8. Submit a pull request from your fork to the main DVSPortal repository.

Before contributing, please read the contribution guidelines in the CONTRIBUTING.md file.

## License

DVSPortal is released under the MIT License. See the LICENSE file for more details.

## Acknowledgements

This project is developed and maintained by [Your Name or Organization]. Contributions from the open-source community are welcome.
