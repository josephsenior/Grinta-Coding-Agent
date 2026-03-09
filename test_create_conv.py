import urllib.request, json  
req = urllib.request.Request('http://127.0.0.1:3001/api/v1/conversations', data=b'{}', headers={'Content-Type': 'application/json'})  
try:  
    r = urllib.request.urlopen(req)  
    print(r.read().decode())  
except Exception as e:  
    print(type(e), e) 
