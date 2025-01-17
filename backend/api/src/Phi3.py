from .rag_modules.LlmApiClient import LlmApiClient
from .infraestructure.ConversationRepository import ConversationRepository
from .infraestructure.DbContext import DbContext
from colorama import Fore, init
from huggingface_hub import login
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
import os
import torch

class Phi3():

    def __init__(self) -> None:

        self.db = ConversationRepository(DbContext())

        self.use_local = torch.cuda.is_available()
        self.use_local = False
        if self.use_local:
            self.inititalize_local()
        self.initialize_remote()

        # Instructions
        self.instructions = "\n".join([
            "You are an expert in mental health, trained to provide empathetic and supportive guidance to individuals seeking help.",
            "Your primary objective is to engage in meaningful conversations about mental health, asking insightful questions and offering thoughtful, compassionate responses.",
            "Avoid discussing or answering questions that are unrelated to mental health, such as topics about coding or other technical subjects.",
            "Always base your responses on the entire context of the conversation, ensuring you remember and reference all previous messages to provide continuity and relevance.",
            "Handle all user data with the utmost confidentiality and remind users to be cautious about sharing sensitive personal health information.",
            "Maintain a calm and supportive tone throughout all interactions, ensuring users feel heard and understood.",
            "Encourage users to express their thoughts and feelings openly, validate their experiences, and offer guidance or coping strategies when appropriate.",
            "If a user deviates from the topic of mental health, gently steer the conversation back to relevant topics to provide the most effective support."
        ])

    def predict(self, conversation_id: int, user_input: str):

        # Create context
        messages = self.create_context(conversation_id, user_input)

        # Generate response
        generated_text = ""
        if self.use_local:

            # Create prompt with context
            prompt_with_context = self.pipe.tokenizer.apply_chat_template(messages, tokenize=False)

            # Generate response using the model locally
            outputs = self.pipe(
                prompt_with_context,
                max_new_tokens=500,
                do_sample=True,
                num_beams=1,
                temperature=0.3,
                top_k=50,
                top_p=0.95,
                max_time= 600
            )
            generated_text = outputs[0]['generated_text'][len(prompt_with_context):].strip()

            # Remove the text after the word "(Note:"
            generated_text = generated_text.split("(Note:")[0].strip()

            # Remove the text after the word "Note:", "\n\n"
            generated_text = generated_text.split("Note:")[0].strip()
            generated_text = generated_text.split("\n\n")[0].strip()

        else:
            generated_text = self.api_client.predict(messages)

        # Create the summary of the conversation
        #summary = self.create_summary(messages[1:])
        summary = "Chat"
        
        # Keep only the first 5 words
        summary = ' '.join(summary.split(" ")[:5])
        
        self.db.update_summary(conversation_id, summary)

        # Return generated text
        return generated_text, summary
    
    def create_context(self, conversation_id: str, user_input: str) -> str:
        """
        Create the context for the conversation, including instructions and history.
        ...
        Parameters
        ----------
        conversation_id : str
            The conversation id to retrieve the history.
        """
        
        # Get the messages from the conversation
        conversation = self.db.get_messages(conversation_id)
        messages = conversation['messages']
        
        # Create an array with the messages splitting the user input and the bot output
        history = [ {"role": "assistant", "content": self.instructions} ]
        for message in messages:
            history.append({ "role": "user", "content": message['user_message'] })
            history.append({ "role": "assistant", "content": message['bot_response'] })

        history.append({"role": "user", "content": user_input})

        return history

    def inititalize_local(self):

        token = os.getenv("HF_API_TOKEN")
        login(token=token)
        print(Fore.CYAN + f"TOKEN={token}")

        # Settings
        model_name = 'acorreal/phi3-mental-health'
        adapter_name = 'acorreal/adapter-phi-3-mini-mental-health'
        compute_dtype = torch.bfloat16

        # Load model
        model = AutoModelForCausalLM.from_pretrained(model_name, trust_remote_code=True, torch_dtype=compute_dtype)
        model = PeftModel.from_pretrained(model, adapter_name)
        model = model.merge_and_unload()
        print(Fore.MAGENTA + 'Model loaded')

        # Load tokenizer
        tokenizer = AutoTokenizer.from_pretrained(adapter_name)
        print(Fore.MAGENTA + 'Tokenizer loaded')

        self.pipe = pipeline("text-generation", model=model, tokenizer=tokenizer)

    def initialize_remote(self):
        """
        Initialize the API client to interact with the fine-tuned model deployed on the cloud.
        """
        api_url = os.getenv("FINE_TUNED_MODEL_URL")
        api_token = os.getenv("FINE_TUNED_MODEL_API_KEY")
        self.api_client = LlmApiClient(api_url, api_token)

    def create_summary(self, messages: list) -> str:
        """
        Create a summary of the conversation based on the messages.
        ...
        Parameters
        ----------
        messages: list
            The list of messages in the conversation.
        """
        
        # Get the chat history
        summary = self.api_client.predict(messages + [
            {
                'role': 'system',
                'content': f"You are a helpful assistant trained to generate the best sentence that summarizes the conversation. Your task is to provide a concise summary in a single sentence (maximum 5 words) that captures the main topic or key event discussed."
            }
        ])

        print(Fore.YELLOW + f"Summary: {summary}")
        
        return summary


