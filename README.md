# print-client

This Python program receives messages over a GCP PubSub subscription and sends them to a specified printer for printing. 

This program only runs on Windows and assumes Python v3.x as a minimum version.

It assumes a specific message structure:
```
{
    "data": BINARY_CONTENT
    "attributes": {
        "order_number": "an integer representing the number of this order",
        "event_date": "a date specifed in ISO8601 format string of 'YYYY-MM-DD'",
        "reprint": "an optional attribute that indicates this is a reprint request"
    }
}
```
