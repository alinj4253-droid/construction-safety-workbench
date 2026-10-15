await page.goto('http://127.0.0.1:8010/',{waitUntil:'domcontentloaded'});
return await tabbit.observe({frames:'none',maxChars:3500});
