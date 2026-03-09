import urllib.request  
print(urllib.request.urlopen('http://127.0.0.1:3001/api/health/live').read())  
