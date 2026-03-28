using Microsoft.AspNetCore.Identity;

namespace MixerAI.Backend.Entities;

public class ApplicationUser : IdentityUser
{
    // Miesto pre custom profilové polia (Full Name, AvatarUrl, atď.)
    // Zatiaľ úplne postačuje zabudovaný Email / Username.
    
    public ICollection<MixJob> MixJobs { get; set; } = new List<MixJob>();
}
