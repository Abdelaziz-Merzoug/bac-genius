const OpenAI = require("openai");

const client = new OpenAI({
});

async function main() {
  try {

    const response = await client.chat.completions.create({
      model: "gpt-5.5",
      messages: [
        {
          role: "user",
        }
      ]
    });

    console.log("\nSUCCESS");
    console.log(response.choices[0].message.content);
  } catch (error) {
    console.error("\nFAILED");
    console.error("Status:", error.status);
    console.error("Message:", error.message);
  }
}

main();
