"""Utility module for generating file viewer HTML content."""

import base64
import mimetypes
import os


def generate_file_viewer_html(file_path: str) -> str:
    """Generate HTML content for viewing different file types.

    Args:
        file_path: The absolute path to the file

    Returns:
        str: HTML content for viewing the file

    Raises:
        ValueError: If the file extension is not supported

    """
    file_extension = os.path.splitext(file_path)[1].lower()
    file_name = os.path.basename(file_path)
    supported_extensions = ['.pdf', '.png', '.jpg', '.jpeg', '.gif']
    if file_extension not in supported_extensions:
        msg = f'Unsupported file extension: {file_extension}. Supported extensions are: {", ".join(supported_extensions)}'
        raise ValueError(
            msg,
        )
    if not os.path.exists(file_path):
        msg = f'File not found locally: {file_path}. Please download the file to the local machine and try again.'
        raise ValueError(
            msg,
        )
    file_content = None
    mime_type = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'
    if file_extension in ['.pdf', '.png', '.jpg', '.jpeg', '.gif', '.bmp']:
        with open(file_path, 'rb') as file:
            file_content = base64.b64encode(file.read()).decode('utf-8')
    else:
        with open(file_path, encoding='utf-8') as file:
            file_content = file.read()
    return f"""<!DOCTYPE html>\n<html lang="en">\n<head>\n    <meta charset="UTF-8">\n    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n    <title>File Viewer - {
        file_name
    }</title>\n    <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>\n    <style>\n        body, html {{ margin: 0; padding: 0; height: 100%; overflow: hidden; font-family: Arial, sans-serif; }}\n        #viewer-container {{ width: 100%; height: 100vh; overflow: auto; }}\n        .page {{ margin: 10px auto; box-shadow: 0 0 10px rgba(0,0,0,0.3); }}\n        .text-content {{ margin: 20px; white-space: pre-wrap; font-family: monospace; line-height: 1.5; }}\n        .error {{ color: red; margin: 20px; }}\n        img {{ max-width: 100%; margin: 20px auto; display: block; }}\n    </style>\n</head>\n<body>\n    <div id="viewer-container"></div>\n    <script>\n    const filePath = "{
        file_path
    }";\n    const fileExtension = "{file_extension}";\n    const fileContent = `{
        (
            file_content
            if file_extension not in ['.pdf', '.png', '.jpg', '.jpeg', '.gif', '.bmp']
            else ''
        )
    }`;\n    const fileBase64 = "{
        (
            file_content
            if file_extension in ['.pdf', '.png', '.jpg', '.jpeg', '.gif', '.bmp']
            else ''
        )
    }";\n    const mimeType = "{
        mime_type
    }";\n    const container = document.getElementById('viewer-container');\n\n    async function loadContent() {{\n        try {{\n            if (fileExtension === '.pdf') {{\n                pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';\n                const binaryString = atob(fileBase64);\n                const bytes = new Uint8Array(binaryString.length);\n                for (let i = 0; i < binaryString.length; i++) {{\n                    bytes[i] = binaryString.charCodeAt(i);\n                }}\n\n                const loadingTask = pdfjsLib.getDocument({{data: bytes.buffer}});\n                const pdf = await loadingTask.promise;\n\n                // Get total number of pages\n                const numPages = pdf.numPages;\n\n                // Render each page\n                for (let pageNum = 1; pageNum <= numPages; pageNum++) {{\n                    const page = await pdf.getPage(pageNum);\n\n                    // Set scale for rendering\n                    const viewport = page.getViewport({{ scale: 1.5 }});\n\n                    // Create canvas for rendering\n                    const canvas = document.createElement('canvas');\n                    canvas.className = 'page';\n                    canvas.width = viewport.width;\n                    canvas.height = viewport.height;\n                    container.appendChild(canvas);\n\n                    // Render PDF page into canvas context\n                    const context = canvas.getContext('2d');\n                    const renderContext = {{\n                        canvasContext: context,\n                        viewport: viewport\n                    }};\n\n                    await page.render(renderContext).promise;\n                }}\n            }} else if (['.png', '.jpg', '.jpeg', '.gif', '.bmp'].includes(fileExtension)) {{\n                const img = document.createElement('img');\n                img.src = `data:${{mimeType}};base64,${{fileBase64}}`;\n                img.alt = filePath.split('/').pop();\n                container.appendChild(img);\n            }} else {{\n                const pre = document.createElement('pre');\n                pre.className = 'text-content';\n                pre.textContent = fileContent;\n                container.appendChild(pre);\n            }}\n        }} catch (error) {{\n            console.error('Error:', error);\n            container.innerHTML = `<div class="error"><h2>Error loading file</h2><p>${{error.message}}</p></div>`;\n        }}\n    }}\n\n    window.onload = loadContent;\n    </script>\n</body>\n</html>"""
