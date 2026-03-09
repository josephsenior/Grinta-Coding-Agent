import urllib.request  
try:  
    with urllib.request.urlopen('http://127.0.0.1:3000/api/v1/health') as r:  
        print(r.read())  
except Exception as e:  
    print(type(e), e)  
