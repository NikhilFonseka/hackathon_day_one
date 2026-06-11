from google import genai

# Initialize the client with your hardcoded API key
client = genai.Client(api_key="AQ.Ab8RN6LZm-bZoLkjmtKx0YSk2dKdCE6wPK_wYes79q8TexuSMg")
<<<<<<< Updated upstream
=======
def askgemini(ask):
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=ask,
        )
        print(response.text)
>>>>>>> Stashed changes

try:
    # Generate content using the fast gemini-2.5-flash model
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents='enter the command here',
    )
    print(response.text)

except Exception as e:
    print(f"An error occurred: {e}")