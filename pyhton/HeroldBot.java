import net.dv8tion.jda.api.JDABuilder;
import net.dv8tion.jda.api.entities.Member;
import net.dv8tion.jda.api.entities.channel.concrete.TextChannel;
import net.dv8tion.jda.api.events.interaction.command.SlashCommandInteractionEvent;
import net.dv8tion.jda.api.hooks.ListenerAdapter;
import javax.security.auth.login.LoginException;
import java.util.logging.Logger;
import java.util.logging.Level;


public class DiscordLogging {
    // Declares a logger for the "discord" namespace
    private static final Logger logger = Logger.getLogger("discord");
    public static void main(String[] args) {
        // Sets the logging level to INFO (or Level.FINE for debug-level)
        logger.setLevel(Level.FINE);

        // Example usage of the logger
        logger.info("This is an info message");
        logger.fine("This is a fine/debug message");
    }
}

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
            // Check permissions, etc. (you can implement your own permission logic)
            Member member = event.getMember();
            if (member != null && member.getRoles().stream().anyMatch(role -> role.getName().equals("Moderator"))) {
                event.reply("✅ Logger works!").queue();
            } else {
                event.reply("⛔ You don't have permission to use this command!").setEphemeral(true).queue();
            }
        }
    }
}