load("@stdlib//json", json="json")
capture = json.loads('{"body":"card.cvv=999&note=a%2Bb+c", "revealed":"123"}')
