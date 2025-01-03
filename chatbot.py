import json
import os
import sys
import time
import pandas as pd
from typing import List
from datetime import datetime
import requests
import firebase_admin
from firebase_admin import credentials, firestore, db as realtime_db


from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI 
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent
from cdp_langchain.agent_toolkits import CdpToolkit
from cdp_langchain.utils import CdpAgentkitWrapper
from cdp_langchain.tools import CdpTool
from pydantic import BaseModel, Field
from cdp import *

wallet_data_file = "wallet_data.txt"
db = None

class TransferInput(BaseModel):
    recipient_address: str = Field(..., description="The recipient wallet address")
    amount: str = Field(..., description="The amount to transfer")

class SignMessageInput(BaseModel):
    message: str = Field(..., description="The message to sign")

class RewardInput(BaseModel):
    total_reward: str = Field(..., description="The total reward amount to distribute")

def initialize_firebase():
    try:
        cred = credentials.Certificate("./firebaseconfig.json")
        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://sathoshi-470e1-default-rtdb.firebaseio.com/'
        })
        return realtime_db
    except Exception as e:
        print(f"Error initializing Firebase: {e}")
        return None

def store_leaderboard(leaderboard):
    """Store leaderboard and update leaderboard history."""
    try:
        # Get references to Realtime Database paths
        leaderboard_ref = db.reference('/leaderboard')
        history_ref = db.reference('/leaderboard_history')

        # Current timestamp
        current_time = datetime.now().isoformat()

        # Format leaderboard data with rankings
        leaderboard_data = {
            "entries": {
                str(rank + 1): {
                    "rank": rank + 1,
                    "twitter_handle": entry["twitter_handle"],
                    "post_link": entry["post_link"],
                    "score": entry["score"],
                    "wallet_address": entry["wallet_address"]
                }
                for rank, entry in enumerate(leaderboard)
            },
            "metadata": {
                "timestamp": current_time,
                "total_participants": len(leaderboard),
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        }

        # Update current leaderboard
        leaderboard_ref.child('current').set(leaderboard_data)

        # Add to history with a unique key based on timestamp
        history_key = current_time.replace(':', '-').replace('.', '-')
        history_ref.child(history_key).set(leaderboard_data)

        print("Leaderboard and history stored in Firebase successfully.")
        print("Current leaderboard data structure:", json.dumps(leaderboard_data, indent=2))
    except Exception as e:
        print(f"Error storing leaderboard: {e}")

def store_transaction(transaction_details):
    """Store transaction details in Firebase."""
    try:
        # Get reference to transactions path
        transaction_ref = db.reference('/transactions')

        # Create a unique key based on timestamp
        timestamp = datetime.now().isoformat()
        transaction_key = timestamp.replace(':', '-').replace('.', '-')

        # Format transaction data
        transaction_data = {
            "wallet_address": transaction_details.get("wallet_address", ""),
            "leaderboard_signature": transaction_details.get("leaderboard_signature", ""),
            "distribution_results": transaction_details.get("distribution_results", []),
            "timestamp": timestamp
        }

        # Store transaction with timestamp
        transaction_ref.child(transaction_key).set(transaction_data)

        print("Transaction details stored in Firebase successfully.")
    except Exception as e:
        print(f"Error storing transaction details: {e}")




def search_tweets(query, bearer_token):
    """Search for tweets with a specific query."""
    url = "https://api.twitter.com/2/tweets/search/recent"
    headers = {
        "Authorization": f"Bearer {bearer_token}"
    }
    # Get today's date in the required format
    today = datetime.now().strftime("%Y-%m-%dT00:00:00Z")
    params = {
        "query": query,
        "start_time": today,
        "tweet.fields": "created_at,public_metrics,author_id",
        "expansions": "author_id",
        "user.fields": "username"
    }

    response = requests.get(url, headers=headers, params=params)

    if response.status_code == 429:
        # Too Many Requests
        print("Rate limit exceeded. Waiting before retrying...")
        time.sleep(15 * 60)  # Wait for 15 minutes
        return search_tweets(query, bearer_token)
    elif response.status_code != 200:
        raise Exception(f"Request returned an error: {response.status_code} {response.text}")

    return response.json()

def calculate_score(metrics):
    """Calculate score based on tweet metrics."""
    return (
        metrics.get('retweet_count', 0) * 2 +
        metrics.get('reply_count', 0) * 1 +
        metrics.get('like_count', 0) * 3 +
        metrics.get('quote_count', 0) * 2 +
        metrics.get('bookmark_count', 0) * 1 +
        metrics.get('impression_count', 0) * 0.1
    )

def get_twitter_leaderboard():
    """Get Twitter leaderboard data."""
    leaderboard = []
    # Load your Bearer Token from a secure location
    with open('config.json') as f:
        config = json.load(f)
    bearer_token = config['BEARER_TOKEN']

    try:
        # Search for tweets containing all three terms
        query = "@basedindia #indiaonchain"
        # result = search_tweets(query, bearer_token)
        # take result from twitter_data_20241207_185113.json
        result = json.load(open("data.json"))

        # # Store raw Twitter API response in a JSON file
        # timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # filename = f"twitter_data_{timestamp}.json"
        # with open(filename, 'w', encoding='utf-8') as f:
        #     json.dump(result, f, indent=2, ensure_ascii=False)

        # print(f"Twitter API response saved to {filename}")
        print(result)

        # Prepare data for leaderboard
        tweets_data = []
        users = {user['id']: user['username'] for user in result.get('includes', {}).get('users', [])}

        for tweet in result.get('data', []):
            metrics = tweet['public_metrics']
            score = calculate_score(metrics)
            twitter_handle = users.get(tweet['author_id'], 'unknown')
            post_link = f"https://x.com/{twitter_handle}/status/{tweet['id']}"
            wallet_address = "0xACa55b37f61406E16821dDE30993348bac6fC456"

            tweets_data.append({
                'twitter_handle': twitter_handle,
                'post_link': post_link,
                'score': score,
                'wallet_address': wallet_address
            })

        # Sort tweets by score

        leaderboard = sorted(tweets_data, key=lambda x: x['score'], reverse=True)
        print("leaderboard")
        print(leaderboard)
        store_leaderboard(leaderboard)
        return leaderboard

    except Exception as e:
        print(f"Error: {e}")
        return []

def transfer_usdc(wallet: Wallet, recipient_address: str, amount: str) -> str:
    """Transfer USDC to specified address."""
    try:
        # Request USDC from faucet before transfer
        faucet_tx = wallet.faucet(asset_id="usdc")
        faucet_tx.wait()
        print("Received USDC from faucet")

        # Perform the transfer
        transfer = wallet.transfer(float(amount), "usdc", recipient_address)
        result = transfer.wait()
        return f"Successfully transferred {amount} USDC to {recipient_address}"
    except Exception as e:
        return f"Failed to transfer USDC: {str(e)}"

def sign_message(wallet: Wallet, message: str) -> str:
    """Sign message using EIP-191 hash."""
    payload_signature = wallet.sign_payload(hash_message(message)).wait()
    return f"The payload signature {payload_signature}"

def read_leaderboard() -> pd.DataFrame:
    """Read and return the leaderboard data."""
    try:
        leaderboard = get_twitter_leaderboard()
        df = pd.DataFrame(leaderboard)
        return df.head(3)  # Get top 3 entries
    except FileNotFoundError:
        print("Leaderboard file not found!")
        return None

def sign_and_distribute_rewards(wallet: Wallet, total_reward: str) -> List[str]:
    results = []
    """Sign leaderboard and distribute rewards to top 3 wallets."""
    # Read leaderboard
    df = read_leaderboard()
    if df is None:
        return ["Error: Leaderboard not found"]

    try:
        # Sign the leaderboard data
        leaderboard_data = df.to_json()
        signature = wallet.sign_payload(hash_message(leaderboard_data)).wait()

        # Convert signature to string format
        signature_str = str(signature)
        # Transaction and signature details
        transaction_details = {
            "wallet_address": wallet.default_address.address_id,
            "leaderboard_signature": signature_str,
            "leaderboard_data": leaderboard_data,
            "distribution_results": results,
        }
        # Store signature onchain using a smart contract invocation
        storage_contract_abi = [
            {
                "inputs": [
                    {"internalType": "string", "name": "data", "type": "string"}
                ],
                "name": "store",
                "outputs": [],
                "stateMutability": "nonpayable",
                "type": "function"
            }
        ]

        # Replace with your deployed storage contract address
        storage_contract_address = "0x252558FBB8eaF442604833974e414FEF41F5784c"

        # Store the signature on-chain
        store_tx = wallet.invoke_contract(
            contract_address=storage_contract_address,
            method="store",
            args={"data": signature_str},
            abi=storage_contract_abi
        ).wait()

        # Calculate reward per wallet (equal distribution)
        reward_amount = float(total_reward) / 3
        reward_per_wallet = f"{reward_amount:.6f}"

        # Transfer rewards to top 3 wallets
        results = []
        for _, row in df.iterrows():
            command = transfer_usdc(wallet, row['wallet_address'], reward_per_wallet)
            results.append(command)

        return [
            f"Leaderboard signature: {signature_str}",
            f"Signature stored onchain with transaction hash: {store_tx.transaction_hash}",
            f"Agent wallet address: {wallet.default_address.address_id}",
            "Reward distribution:",
            *results
        ]
    except Exception as e:
        return [f"Error during reward distribution: {str(e)}"]

def add_reward_tool(tools, agentkit):
    reward_tool = CdpTool(
        name="distribute_daily_rewards",
        description="Sign the leaderboard and distribute rewards to top 3 wallets",
        cdp_agentkit_wrapper=agentkit,
        args_schema=RewardInput,
        func=sign_and_distribute_rewards
    )
    return tools + [reward_tool]

def initialize_agent():
    llm = ChatOpenAI(model="gpt-4o-mini")
    wallet_data = None

    if os.path.exists(wallet_data_file):
        with open(wallet_data_file) as f:
            wallet_data = f.read()

    values = {}
    if wallet_data is not None:
        values = {"cdp_wallet_data": wallet_data}

    agentkit = CdpAgentkitWrapper(**values)
    wallet_data = agentkit.export_wallet()
    with open(wallet_data_file, "w") as f:
        f.write(wallet_data)

    cdp_toolkit = CdpToolkit.from_cdp_agentkit_wrapper(agentkit)
    tools = cdp_toolkit.get_tools()

    transfer_tool = CdpTool(
        name="transfer_usdc",
        description="Transfer USDC to a specified wallet address",
        cdp_agentkit_wrapper=agentkit,
        args_schema=TransferInput,
        func=transfer_usdc,
    )

    sign_tool = CdpTool(
        name="sign_message",
        description="Sign a message using EIP-191",
        cdp_agentkit_wrapper=agentkit,
        args_schema=SignMessageInput,
        func=sign_message,
    )

    all_tools = tools + [transfer_tool, sign_tool]
    all_tools = add_reward_tool(all_tools, agentkit)
    memory = MemorySaver()

    return create_react_agent(
        llm,
        tools=all_tools,
        checkpointer=memory,
        state_modifier="You are a helpful agent that can interact onchain using the Coinbase Developer Platform Agentkit. You are empowered to interact onchain using your tools. If you ever need funds, you can request them from the faucet if you are on network ID `base-sepolia`. If not, you can provide your wallet details and request funds from the user. If someone asks you to do something you can't do with your currently available tools, you must say so, and encourage them to implement it themselves using the CDP SDK + Agentkit, recommend they go to docs.cdp.coinbase.com for more informaton. Be concise and helpful with your responses. Refrain from restating your tools' descriptions unless it is explicitly requested.",
    )

def run_autonomous_mode(agent_executor, config, interval=10):
    print("Starting autonomous mode...")
    while True:
        try:
            thought = (
                "Be creative and do something interesting on the blockchain. "
                "Choose an action or set of actions and execute it that highlights your abilities."
            )

            for chunk in agent_executor.stream(
                {"messages": [HumanMessage(content=thought)]}, config):
                if "agent" in chunk:
                    print(chunk["agent"]["messages"][0].content)
                elif "tools" in chunk:
                    print(chunk["tools"]["messages"][0].content)
                print("-------------------")

            time.sleep(interval)

        except KeyboardInterrupt:
            print("Goodbye Agent!")
            sys.exit(0)

def run_chat_mode(agent_executor, config):
    print("Starting chat mode... Type 'exit' to end.")
    while True:
        try:
            user_input = input("\nUser: ")
            if user_input.lower() == "exit":
                break

            for chunk in agent_executor.stream(
                {"messages": [HumanMessage(content=user_input)]}, config):
                if "agent" in chunk:
                    print(chunk["agent"]["messages"][0].content)
                elif "tools" in chunk:
                    print(chunk["tools"]["messages"][0].content)
                print("-------------------")

        except KeyboardInterrupt:
            print("Goodbye Agent!")
            sys.exit(0)

def run_rewards_mode(agent_executor, config):
    print("Starting rewards distribution mode...")
    try:
        reward_amount = "0.003"  # Default reward amount (0.001 USDC per wallet for top 3)
        thought = f"Please distribute {reward_amount} as daily rewards to the top 3 wallets in the leaderboard and sign the leaderboard data."

        for chunk in agent_executor.stream(
            {"messages": [HumanMessage(content=thought)]}, config):
            if "agent" in chunk:
                print(chunk["agent"]["messages"][0].content)
            elif "tools" in chunk:
                print(chunk["tools"]["messages"][0].content)
            print("-------------------")

    except KeyboardInterrupt:
        print("Goodbye Agent!")
        sys.exit(0)

def choose_mode():
    print("\nAvailable modes:")
    print("1. chat    - Interactive chat mode")
    print("2. auto    - Autonomous action mode")
    print("3. rewards - Distribute daily rewards")

    choice = input("\nChoose a mode (enter number or name): ").lower().strip()
    if choice in ["1", "chat"]:
        return "chat"
    elif choice in ["2", "auto"]:
        return "auto"
    elif choice in ["3", "rewards"]:
        return "rewards"
    print("Invalid choice. Please try again.")

def main():
    global db
    db = initialize_firebase()
    if not db:
        print("Failed to initialize Firebase. Exiting...")
        return

    agent_executor = initialize_agent()
    config = {
        "configurable": {
            "thread_id": "CDP Agentkit Chatbot Example!",
            "checkpoint_ns": "default_namespace",
            "checkpoint_id": "default_checkpoint"
        }
    }

    run_rewards_mode(agent_executor=agent_executor, config=config)

if __name__ == "__main__":
    print("Starting Agent...")
    main()