using Microsoft.AspNetCore.Identity.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore;
using MixerAI.Backend.Entities;

namespace MixerAI.Backend.Data;

public class ApplicationDbContext : IdentityDbContext<ApplicationUser>
{
    public ApplicationDbContext(DbContextOptions<ApplicationDbContext> options)
        : base(options)
    {
    }

    public DbSet<MixJob> MixJobs { get; set; }
    public DbSet<Track> Tracks { get; set; }

    protected override void OnModelCreating(ModelBuilder builder)
    {
        base.OnModelCreating(builder);

        // Mapovanie tabuliek a vzťahov
        builder.Entity<Track>(entity =>
        {
            entity.HasKey(e => e.Id);
            entity.HasOne(t => t.User)
                .WithMany() // Can add ICollection<Track> to ApplicationUser later if needed
                .HasForeignKey(t => t.UserId)
                .OnDelete(DeleteBehavior.Cascade);
        });

        builder.Entity<MixJob>(entity =>
        {
            entity.HasKey(e => e.Id);
            
            // Jeden user môže mať veľa mixov
            entity.HasOne(m => m.User)
                .WithMany(u => u.MixJobs)
                .HasForeignKey(m => m.UserId)
                .OnDelete(DeleteBehavior.Cascade); // ak sa zmaže user, zmažú sa aj jeho mixy
        });
    }
}
