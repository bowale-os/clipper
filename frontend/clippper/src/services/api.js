const API_URL = import.meta.env.VITE_API_URL

export async function hitFastAPIBackend(){
    try {
        const response = await fetch(
            `${API_URL}/hit-it`, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                },
        });

        if (!response.ok){
            throw new Error("HTTP Error")
        }

        const data = await response.json();
        console.log(data);
    
    } catch (error) {
        console.log(`This weird error occurred: ${error}`)
    }
}