from google import genai

client = genai.Client(api_key="AQ.Ab8RN6LZm-bZoLkjmtKx0YSk2dKdCE6wPK_wYes79q8TexuSMg")
def askgemini(ask):
    try:
        # Generate content using the fast gemini-2.5-flash model
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=ask,
        )
        print(response.text)

    except Exception as e:
        print(f"An error occurred: {e}")