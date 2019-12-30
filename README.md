# print-client

This Python program receives messages over a GCP PubSub subscription and sends them to a specified printer for printing. 

This program only runs on Windows and assumes Python v3.x as a minimum version.

It assumes a specific message structure:
```
{
    "data": Base64-encoded PDF
    "attributes": {
        "order_number": "an integer representing the number of this order",
        "event_id": "any string that serves to effectively group printing requests",
        "reprint": "an optional attribute that indicates this is a reprint request"
    }
}
```
