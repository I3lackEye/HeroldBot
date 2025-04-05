import net.dv8tion.jda.api.JDABuilder;
import net.dv8tion.jda.api.entities.Member;
import net.dv8tion.jda.api.entities.channel.concrete.TextChannel;
import net.dv8tion.jda.api.events.interaction.command.SlashCommandInteractionEvent;
import net.dv8tion.jda.api.hooks.ListenerAdapter;
import javax.security.auth.login.LoginException;

public class HeroldBot extends ListenerAdapter {
    
    public static void main(String[] args) throws LoginException {
        // Create JDA instance using your bot token
        JDABuilder.createDefault(System.getenv("TOKEN"))
                  .addEventListeners(new HeroldBot())
                  .build();
    }

    @Override
    public void onSlashCommandInteraction(SlashCommandInteractionEvent event) {
        // Example for a simple command: /test_log
        if (event.getName().equals("test_log")) {
            // Check permissions, etc.
            Member member = event.getMember();
            if (member != null && member.getRoles().stream().anyMatch(role -> role.getName().equals("Moderator"))) {
                event.reply("✅ Logger works!").queue();
            } else {
                event.reply("⛔ You don't have permission to use this command!").setEphemeral(true).queue();
            }
        }
    }
}

