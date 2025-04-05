package com.heroldbot;

import net.dv8tion.jda.api.JDABuilder;
import net.dv8tion.jda.api.entities.Activity;
import net.dv8tion.jda.api.hooks.ListenerAdapter;
import net.dv8tion.jda.api.events.interaction.command.SlashCommandInteractionEvent;
import javax.security.auth.login.LoginException;

public class Bot extends ListenerAdapter {

    public static void main(String[] args) throws LoginException {
        // Get token form env variable
        String token = System.getenv("TOKEN");
        
        JDABuilder builder = JDABuilder.createDefault(token);
        builder.setActivity(Activity.playing("Tournament Management"));
        builder.addEventListeners(new Bot());
        builder.build();
    }

    @Override
    public void onSlashCommandInteraction(SlashCommandInteractionEvent event) {
        if (event.getName().equals("test_log")) {
            event.reply("✅ Logger works!").queue();
        }
        // place more slash commands here
    }
}